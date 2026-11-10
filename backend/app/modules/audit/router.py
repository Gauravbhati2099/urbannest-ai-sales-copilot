from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from uuid import UUID

import jwt
import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.dependencies import CurrentUser, DatabaseSession
from app.core.rate_limit import rate_limit_setting
from app.core.security import decode_access_token
from app.db.config import get_database_url
from app.db.models import AuditEvent, AuditReadCursor, Task, User
from app.db.session import SessionLocal
from app.modules.audit.schemas import (
    AuditEventRead,
    AuditFeedResponse,
    AuditReadResponse,
    AuditUnreadCount,
)
from app.modules.audit.service import mark_events_read, unread_count, visible_audit_statement

router = APIRouter(prefix="/audit", tags=["audit and notifications"])


def _advisory_lock_key(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def _try_acquire_advisory_lock(connection: psycopg.Connection, key: str) -> bool:
    return bool(
        connection.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (_advisory_lock_key(key),),
        ).fetchone()[0]
    )


def _release_advisory_lock(connection: psycopg.Connection, key: str) -> None:
    connection.execute(
        "SELECT pg_advisory_unlock(%s)",
        (_advisory_lock_key(key),),
    )


def _connect_limited_stream(user_id: UUID) -> psycopg.Connection:
    global_limit = rate_limit_setting("AUDIT_STREAMS_GLOBAL_LIMIT", 10)
    per_user_limit = rate_limit_setting("AUDIT_STREAMS_PER_USER_LIMIT", 2)
    connection = psycopg.connect(
        get_database_url().set(drivername="postgresql").render_as_string(
            hide_password=False
        ),
        autocommit=True,
    )
    try:
        for global_slot in range(global_limit):
            global_key = f"audit-stream:global:{global_slot}"
            if not _try_acquire_advisory_lock(connection, global_key):
                continue
            for user_slot in range(per_user_limit):
                user_key = f"audit-stream:user:{user_id}:{user_slot}"
                if _try_acquire_advisory_lock(connection, user_key):
                    return connection
            _release_advisory_lock(connection, global_key)
        connection.close()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Audit notification stream capacity is full",
            headers={"Retry-After": "15"},
        )
    except (HTTPException, psycopg.Error):
        if not connection.closed:
            connection.close()
        raise


@router.get("/events", response_model=AuditFeedResponse)
def list_audit_events(
    current_user: CurrentUser,
    session: DatabaseSession,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AuditFeedResponse:
    cursor = session.get(AuditReadCursor, current_user.id)
    last_read_at = cursor.last_read_at if cursor is not None else None
    events = list(
        session.scalars(
            visible_audit_statement(current_user)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )
    task_ids = [
        event.entity_id
        for event in events
        if event.entity_type == "task" and event.entity_id is not None
    ]
    task_titles = (
        dict(
            session.execute(
                select(Task.id, Task.title).where(
                    Task.team_id == current_user.team_id,
                    Task.id.in_(task_ids),
                )
            ).all()
        )
        if task_ids
        else {}
    )
    return AuditFeedResponse(
        events=[
            AuditEventRead.model_validate(event).model_copy(
                update={
                    "is_read": (
                        event.created_at <= last_read_at
                        if last_read_at is not None
                        else False
                    ),
                    "changes": (
                        {
                            **(event.changes or {}),
                            "task_title": task_titles[event.entity_id],
                        }
                        if event.entity_type == "task"
                        and event.entity_id in task_titles
                        and "task_title" not in (event.changes or {})
                        else event.changes
                    ),
                }
            )
            for event in events
        ],
        unread_count=unread_count(session, current_user, last_read_at),
    )


@router.get("/unread-count", response_model=AuditUnreadCount)
def get_unread_count(
    current_user: CurrentUser,
    session: DatabaseSession,
) -> AuditUnreadCount:
    cursor = session.get(AuditReadCursor, current_user.id)
    last_read_at = cursor.last_read_at if cursor is not None else None
    return AuditUnreadCount(
        unread_count=unread_count(session, current_user, last_read_at)
    )


@router.post("/read", response_model=AuditReadResponse)
def mark_audit_events_read(
    current_user: CurrentUser,
    session: DatabaseSession,
) -> AuditReadResponse:
    return AuditReadResponse(last_read_at=mark_events_read(session, current_user))


def _event_stream(
    connection: psycopg.Connection,
    user_id: UUID,
    auth_version: int,
    token: str,
) -> Iterator[str]:
    try:
        connection.execute("LISTEN audit_events")
        yield ": connected\n\nevent: audit-sync\ndata: {}\n\n"
        while True:
            notification = next(
                connection.notifies(timeout=15.0, stop_after=1),
                None,
            )
            if notification is None:
                try:
                    token_user_id, token_auth_version = decode_access_token(token)
                except jwt.InvalidTokenError:
                    yield "event: auth-revoked\ndata: {}\n\n"
                    return
                if token_user_id != user_id or token_auth_version != auth_version:
                    yield "event: auth-revoked\ndata: {}\n\n"
                    return
                yield ": keep-alive\n\n"
                continue

            try:
                token_user_id, token_auth_version = decode_access_token(token)
            except jwt.InvalidTokenError:
                yield "event: auth-revoked\ndata: {}\n\n"
                return
            if token_user_id != user_id or token_auth_version != auth_version:
                yield "event: auth-revoked\ndata: {}\n\n"
                return
            payload = json.loads(notification.payload)
            event_id = UUID(payload["event_id"])
            team_id = UUID(payload["team_id"])
            with SessionLocal() as session:
                user = session.scalar(select(User).where(User.id == user_id))
                if (
                    user is None
                    or not user.is_active
                    or user.auth_version != auth_version
                ):
                    yield "event: auth-revoked\ndata: {}\n\n"
                    return
                if user.team_id != team_id:
                    continue
                event = session.scalar(
                    visible_audit_statement(user).where(AuditEvent.id == event_id)
                )
                if event is None:
                    continue
                data = json.dumps({"event_id": str(event.id)}, separators=(",", ":"))
                yield f"id: {event.id}\nevent: audit\ndata: {data}\n\n"
    finally:
        connection.close()


@router.get("/stream")
def stream_audit_events(
    current_user: CurrentUser,
    request: Request,
    session: DatabaseSession,
) -> StreamingResponse:
    scheme, separator, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not separator or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    try:
        connection = _connect_limited_stream(current_user.id)
    except psycopg.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audit notification stream is temporarily unavailable",
        ) from exc
    session.close()
    return StreamingResponse(
        _event_stream(connection, current_user.id, current_user.auth_version, token),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
