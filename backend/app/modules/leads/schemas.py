from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import ActivityType, LeadSource, LeadStatus


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    source: LeadSource = LeadSource.MANUAL
    status: LeadStatus = LeadStatus.NEW
    budget_min_inr: int | None = Field(default=None, ge=0)
    budget_max_inr: int | None = Field(default=None, ge=0)
    bhk: int | None = Field(default=None, gt=0)
    preferred_location: str | None = Field(default=None, max_length=160)
    notes: str | None = None
    assigned_to: UUID | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized) is None:
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("budget_max_inr")
    @classmethod
    def validate_budget_range(cls, value: int | None, info) -> int | None:
        minimum = info.data.get("budget_min_inr")
        if value is not None and minimum is not None and minimum > value:
            raise ValueError("Minimum budget must not exceed maximum budget")
        return value


class PublicLeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    budget_min_inr: int | None = Field(default=None, ge=0)
    budget_max_inr: int | None = Field(default=None, ge=0)
    bhk: int | None = Field(default=None, gt=0)
    preferred_location: str | None = Field(default=None, max_length=160)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized) is None:
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("budget_max_inr")
    @classmethod
    def validate_budget_range(cls, value: int | None, info) -> int | None:
        minimum = info.data.get("budget_min_inr")
        if value is not None and minimum is not None and minimum > value:
            raise ValueError("Minimum budget must not exceed maximum budget")
        return value


class LeadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    source: LeadSource | None = None
    status: LeadStatus | None = None
    budget_min_inr: int | None = Field(default=None, ge=0)
    budget_max_inr: int | None = Field(default=None, ge=0)
    bhk: int | None = Field(default=None, gt=0)
    preferred_location: str | None = Field(default=None, max_length=160)
    notes: str | None = None
    assigned_to: UUID | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized) is None:
            raise ValueError("Enter a valid email address")
        return normalized


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    assigned_to: UUID | None
    created_by: UUID | None
    full_name: str
    email: str | None
    phone: str | None
    source: LeadSource
    status: LeadStatus
    budget_min_inr: int | None
    budget_max_inr: int | None
    bhk: int | None
    preferred_location: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ActivityType
    body: str = Field(min_length=1, max_length=10000)
    occurred_at: datetime | None = None

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Activity body must not be blank")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    lead_id: UUID
    actor_id: UUID | None
    type: ActivityType
    body: str
    occurred_at: datetime


class CSVImportResult(BaseModel):
    created_count: int
    rejected_count: int
    created_lead_ids: list[UUID]
    errors: list["CSVRowError"]


class CSVRowError(BaseModel):
    row: int
    message: str
