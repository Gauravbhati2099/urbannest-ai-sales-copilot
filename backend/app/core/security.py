from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.db.models import User

TOKEN_ISSUER = "infinaut-crm-api"
TOKEN_ALGORITHM = "HS256"


@dataclass(frozen=True)
class AuthSettings:
    secret_key: str
    access_token_expire_minutes: int


def get_auth_settings() -> AuthSettings:
    secret_key = os.getenv("JWT_SECRET_KEY", "")
    if len(secret_key.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET_KEY must contain at least 32 bytes")
    if os.getenv("JWT_ALGORITHM", TOKEN_ALGORITHM) != TOKEN_ALGORITHM:
        raise RuntimeError("JWT_ALGORITHM must be HS256")

    try:
        expires_minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    except ValueError as exc:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be an integer") from exc
    if not 5 <= expires_minutes <= 1440:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 5 and 1440")

    return AuthSettings(
        secret_key=secret_key,
        access_token_expire_minutes=expires_minutes,
    )


def create_access_token(user: User) -> tuple[str, int]:
    settings = get_auth_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user.id),
        "ver": user.auth_version,
        "iss": TOKEN_ISSUER,
        "iat": now,
        "exp": expires_at,
        "token_type": "access",
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=TOKEN_ALGORITHM)
    return token, settings.access_token_expire_minutes * 60


def decode_access_token(token: str) -> tuple[UUID, int]:
    settings = get_auth_settings()
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[TOKEN_ALGORITHM],
        issuer=TOKEN_ISSUER,
        options={"require": ["exp", "iat", "iss", "sub", "token_type", "ver"]},
    )
    if payload.get("token_type") != "access":
        raise jwt.InvalidTokenError("Invalid token type")
    try:
        user_id = UUID(payload["sub"])
        auth_version = payload["ver"]
        if not isinstance(auth_version, int) or auth_version < 0:
            raise ValueError("Invalid auth version")
        return user_id, auth_version
    except (ValueError, TypeError, KeyError) as exc:
        raise jwt.InvalidTokenError("Invalid subject") from exc
