from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import LeadTemperature, MessageChannel


class LeadScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    temperature: LeadTemperature
    reason: str = Field(min_length=1, max_length=1000)
    factors: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class LeadScoreRead(LeadScoreResult):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    created_at: datetime
    is_stale: bool
    provider: str
    model: str


class MessageDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: MessageChannel
    tone: Literal["professional", "friendly", "concise", "warm"] = "professional"


class MessageDraftResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=5000)


class MessageDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lead_id: UUID
    channel: MessageChannel
    tone: str
    body: str
    status: str
    created_at: datetime


class NoteExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str = Field(min_length=1, max_length=5000)


class NoteExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_min_inr: int | None = Field(default=None, ge=0)
    budget_max_inr: int | None = Field(default=None, ge=0)
    bhk: int | None = Field(default=None, gt=0)
    preferred_location: str | None = Field(default=None, max_length=160)
    next_task_title: str | None = Field(default=None, max_length=200)
    next_task_due_at: datetime | None = None

    @model_validator(mode="after")
    def validate_extracted_data(self) -> NoteExtractionResult:
        if (
            self.budget_min_inr is not None
            and self.budget_max_inr is not None
            and self.budget_min_inr > self.budget_max_inr
        ):
            raise ValueError("Extracted minimum budget exceeds maximum budget")
        if self.next_task_due_at is not None and self.next_task_due_at.tzinfo is None:
            raise ValueError("Extracted task time must include a timezone")
        if self.next_task_due_at is not None and not self.next_task_title:
            raise ValueError("Extracted task time requires a task title")
        return self
