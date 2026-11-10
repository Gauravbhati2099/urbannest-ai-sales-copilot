from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID | None
    actor_name: str | None
    lead_id: UUID | None
    entity_type: str
    entity_id: UUID | None
    action: str
    summary: str
    changes: dict[str, object] | None
    created_at: datetime
    is_read: bool = False


class AuditFeedResponse(BaseModel):
    events: list[AuditEventRead]
    unread_count: int


class AuditReadResponse(BaseModel):
    last_read_at: datetime


class AuditUnreadCount(BaseModel):
    unread_count: int
