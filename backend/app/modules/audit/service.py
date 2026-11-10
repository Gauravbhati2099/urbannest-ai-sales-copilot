from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    AuditReadCursor,
    AuditVisibility,
    Lead,
    User,
    UserRole,
)

ADMIN_ROLES = {UserRole.OWNER, UserRole.MANAGER}


def visible_audit_statement(user: User):
    statement = select(AuditEvent).where(AuditEvent.team_id == user.team_id)
    if user.role in ADMIN_ROLES:
        return statement

    accessible_team_event = and_(
        AuditEvent.visibility == AuditVisibility.TEAM,
        or_(
            AuditEvent.lead_id.is_(None),
            select(Lead.id)
            .where(
                Lead.id == AuditEvent.lead_id,
                Lead.team_id == user.team_id,
                Lead.assigned_to == user.id,
            )
            .exists(),
        ),
    )
    own_event = and_(
        AuditEvent.visibility == AuditVisibility.ACTOR,
        AuditEvent.actor_id == user.id,
    )
    return statement.where(or_(accessible_team_event, own_event))


def record_audit_event(
    session: Session,
    *,
    team_id: UUID,
    actor_id: UUID | None,
    lead_id: UUID | None,
    entity_type: str,
    entity_id: UUID | None,
    action: str,
    visibility: AuditVisibility,
    summary: str,
    changes: dict[str, object] | None = None,
) -> AuditEvent:
    actor = session.get(User, actor_id) if actor_id is not None else None
    event = AuditEvent(
        team_id=team_id,
        actor_id=actor_id,
        actor_name=actor.full_name if actor is not None else None,
        lead_id=lead_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        visibility=visibility,
        summary=summary,
        changes=changes,
    )
    session.add(event)
    return event


def unread_count(session: Session, user: User, last_read_at: datetime | None) -> int:
    visible_events = visible_audit_statement(user)
    if last_read_at is not None:
        visible_events = visible_events.where(AuditEvent.created_at > last_read_at)
    statement = select(func.count()).select_from(visible_events.subquery())
    return session.scalar(statement) or 0


def mark_events_read(session: Session, user: User) -> datetime:
    cursor = session.get(AuditReadCursor, user.id)
    timestamp = session.scalar(select(func.now()))
    if timestamp is None:
        raise RuntimeError("Database did not return the audit read timestamp")
    if cursor is None:
        cursor = AuditReadCursor(
            user_id=user.id,
            team_id=user.team_id,
            last_read_at=timestamp,
        )
        session.add(cursor)
    else:
        cursor.last_read_at = timestamp
    session.commit()
    return timestamp
