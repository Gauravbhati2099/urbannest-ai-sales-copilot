from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import TaskStatus


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    due_at: datetime
    assigned_to: UUID | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Task title must not be blank")
        return normalized

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus | None = None
    assigned_to: UUID | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    lead_id: UUID
    assigned_to: UUID
    assigned_to_name: str
    created_by: UUID
    title: str
    description: str | None
    due_at: datetime
    status: TaskStatus
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
