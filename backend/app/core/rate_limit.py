from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.security import get_auth_settings
from app.db.models import RateLimitBucket


def rate_limit_setting(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def client_address(request: Request) -> str:
    if request.client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client address unavailable",
        )
    return request.client.host


def _key_hash(scope: str, key: str) -> str:
    secret = get_auth_settings().secret_key.encode("utf-8")
    digest = hmac.new(secret, f"{scope}\0{key}".encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def enforce_rate_limits(
    session: Session,
    *,
    limits: Iterable[tuple[str, str, int]],
    window_seconds: int,
    now: datetime | None = None,
) -> None:
    if window_seconds < 1:
        raise ValueError("Rate-limit window must be positive")
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("Rate-limit timestamp must be timezone-aware")
    epoch = int(current_time.timestamp())
    window_epoch = epoch // window_seconds * window_seconds
    window_start = datetime.fromtimestamp(window_epoch, timezone.utc)
    retry_after = 0
    dialect = session.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert

    for scope, key, limit in limits:
        if limit < 1:
            raise ValueError("Rate-limit maximum must be positive")
        key_hash = _key_hash(scope, key)
        statement = insert(RateLimitBucket).values(
            scope=scope,
            key_hash=key_hash,
            window_start=window_start,
            hit_count=1,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[
                RateLimitBucket.scope,
                RateLimitBucket.key_hash,
                RateLimitBucket.window_start,
            ],
            set_={"hit_count": RateLimitBucket.hit_count + 1},
        ).returning(RateLimitBucket.hit_count)
        hit_count = session.scalar(statement)
        if hit_count is None:
            session.rollback()
            raise RuntimeError("Rate limiter failed to update its shared counter")
        if hit_count > limit:
            retry_after = max(
                retry_after,
                window_seconds - (epoch - window_epoch),
            )

    session.execute(
        delete(RateLimitBucket).where(
            RateLimitBucket.window_start
            < current_time - timedelta(days=1)
        )
    )
    session.commit()

    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests; try again later",
            headers={"Retry-After": str(retry_after)},
        )


def clear_rate_limit(session: Session, *, scope: str, key: str) -> None:
    session.execute(
        delete(RateLimitBucket).where(
            RateLimitBucket.scope == scope,
            RateLimitBucket.key_hash == _key_hash(scope, key),
        )
    )
    session.commit()
