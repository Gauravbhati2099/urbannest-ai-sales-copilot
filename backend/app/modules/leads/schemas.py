from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.normalization import normalize_email, normalize_person_name, normalize_phone_fields
from app.db.models import ActivityType, LeadSource, LeadStatus, UserRole


class PhoneFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str | None = Field(default=None, max_length=40)
    phone_country_code: str | None = Field(default=None, max_length=5)
    phone_region: str | None = Field(default=None, max_length=2)
    phone_national_number: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def normalize_phone(self):
        details = normalize_phone_fields(
            self.phone,
            self.phone_country_code,
            self.phone_region,
            self.phone_national_number,
        )
        object.__setattr__(self, "phone", details.phone)
        object.__setattr__(self, "phone_country_code", details.country_code)
        object.__setattr__(self, "phone_region", details.region)
        object.__setattr__(self, "phone_national_number", details.national_number)
        return self


class LocationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=160)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str = Field(min_length=1, max_length=120)
    country_code: str = Field(min_length=2, max_length=2)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    osm_type: str | None = Field(default=None, pattern=r"^[NWR]$")
    osm_id: int | None = Field(default=None, gt=0)

    @field_validator("display_name", "city", "state", "country")
    @classmethod
    def normalize_location_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Selected location names must not be blank")
        return normalized

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", normalized):
            raise ValueError("Country code must be a two-letter ISO code")
        return normalized


class LeadCreate(PhoneFields):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    source: LeadSource = LeadSource.MANUAL
    status: LeadStatus = LeadStatus.NEW
    budget_min_inr: int | None = Field(default=None, ge=0)
    budget_max_inr: int | None = Field(default=None, ge=0)
    bhk: int | None = Field(default=None, gt=0)
    preferred_location: str | None = Field(default=None, max_length=160)
    location: LocationSelection | None = None
    notes: str | None = None
    assigned_to: UUID | None = None
    allow_duplicate: bool = False

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return normalize_person_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return normalize_email(value)

    @model_validator(mode="after")
    def normalize_location(self):
        if self.location is not None:
            object.__setattr__(self, "preferred_location", self.location.display_name)
        elif self.preferred_location is not None:
            object.__setattr__(
                self, "preferred_location", " ".join(self.preferred_location.split())
            )
        return self

    @field_validator("budget_max_inr")
    @classmethod
    def validate_budget_range(cls, value: int | None, info) -> int | None:
        minimum = info.data.get("budget_min_inr")
        if value is not None and minimum is not None and minimum > value:
            raise ValueError("Minimum budget must not exceed maximum budget")
        return value


class PublicLeadCreate(PhoneFields):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    budget_min_inr: int | None = Field(default=None, ge=0)
    budget_max_inr: int | None = Field(default=None, ge=0)
    bhk: int | None = Field(default=None, gt=0)
    preferred_location: str | None = Field(default=None, max_length=160)
    location: LocationSelection | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return normalize_person_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return normalize_email(value)

    @model_validator(mode="after")
    def normalize_location(self):
        if self.location is not None:
            object.__setattr__(self, "preferred_location", self.location.display_name)
        elif self.preferred_location is not None:
            object.__setattr__(
                self, "preferred_location", " ".join(self.preferred_location.split())
            )
        return self

    @field_validator("budget_max_inr")
    @classmethod
    def validate_budget_range(cls, value: int | None, info) -> int | None:
        minimum = info.data.get("budget_min_inr")
        if value is not None and minimum is not None and minimum > value:
            raise ValueError("Minimum budget must not exceed maximum budget")
        return value


class LeadUpdate(PhoneFields):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    source: LeadSource | None = None
    status: LeadStatus | None = None
    budget_min_inr: int | None = Field(default=None, ge=0)
    budget_max_inr: int | None = Field(default=None, ge=0)
    bhk: int | None = Field(default=None, gt=0)
    preferred_location: str | None = Field(default=None, max_length=160)
    location: LocationSelection | None = None
    notes: str | None = None
    assigned_to: UUID | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_person_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return normalize_email(value)


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    assigned_to: UUID | None
    created_by: UUID | None
    full_name: str
    email: str | None
    phone: str | None
    phone_country_code: str | None
    phone_region: str | None
    phone_national_number: str | None
    source: LeadSource
    status: LeadStatus
    budget_min_inr: int | None
    budget_max_inr: int | None
    bhk: int | None
    preferred_location: str | None
    location: LocationSelection | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class LeadAssigneeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    role: UserRole


class LeadDuplicateCheck(BaseModel):
    duplicate_count: int


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
