from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from app.db.models import EstateInterestStatus, EstateStatus, EstateType, UserRole
from app.modules.leads.schemas import LocationSelection


EstateDetails = dict[str, StrictInt | StrictFloat | str]

DETAIL_FIELDS: dict[EstateType, dict[str, str]] = {
    EstateType.FLAT: {
        "bedrooms": "integer",
        "bathrooms": "integer",
        "built_up_area_sqft": "integer",
        "floor_number": "integer",
        "total_floors": "integer",
        "parking_spaces": "integer",
        "furnishing": "text",
    },
    EstateType.PLOT: {
        "plot_area_sqft": "integer",
        "frontage_ft": "integer",
        "depth_ft": "integer",
        "zoning": "text",
        "facing": "text",
    },
    EstateType.HOUSE: {
        "bedrooms": "integer",
        "bathrooms": "integer",
        "built_up_area_sqft": "integer",
        "plot_area_sqft": "integer",
        "floors": "integer",
        "parking_spaces": "integer",
        "furnishing": "text",
    },
    EstateType.COMMERCIAL_LAND: {
        "plot_area_sqft": "integer",
        "frontage_ft": "integer",
        "zoning": "text",
    },
    EstateType.FARMLAND: {
        "land_area_acres": "number",
        "water_source": "text",
        "soil_type": "text",
    },
    EstateType.FARMHOUSE: {
        "bedrooms": "integer",
        "bathrooms": "integer",
        "built_up_area_sqft": "integer",
        "land_area_acres": "number",
        "parking_spaces": "integer",
        "water_source": "text",
        "furnishing": "text",
    },
}

DETAIL_LABELS = {
    "bedrooms": "Bedrooms",
    "bathrooms": "Bathrooms",
    "built_up_area_sqft": "Built-up area (sq ft)",
    "plot_area_sqft": "Plot area (sq ft)",
    "floor_number": "Floor",
    "total_floors": "Total floors",
    "floors": "Floors",
    "parking_spaces": "Parking spaces",
    "furnishing": "Furnishing",
    "frontage_ft": "Frontage (ft)",
    "depth_ft": "Depth (ft)",
    "zoning": "Zoning",
    "facing": "Facing",
    "land_area_acres": "Land area (acres)",
    "water_source": "Water source",
    "soil_type": "Soil type",
}

NONNEGATIVE_INTEGER_FIELDS = {"floor_number", "parking_spaces"}


def validate_estate_details(
    estate_type: EstateType, details: EstateDetails
) -> EstateDetails:
    allowed = DETAIL_FIELDS[estate_type]
    unknown_fields = set(details) - set(allowed)
    if unknown_fields:
        raise ValueError(
            f"{estate_type.value} does not support: {', '.join(sorted(unknown_fields))}"
        )

    normalized: EstateDetails = {}
    for field_name, value in details.items():
        field_kind = allowed[field_name]
        if field_kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{DETAIL_LABELS[field_name]} must be a whole number")
            if value < (0 if field_name in NONNEGATIVE_INTEGER_FIELDS else 1):
                raise ValueError(f"{DETAIL_LABELS[field_name]} is out of range")
        elif field_kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{DETAIL_LABELS[field_name]} must be a number")
            if value <= 0:
                raise ValueError(f"{DETAIL_LABELS[field_name]} must be greater than zero")
        else:
            if not isinstance(value, str):
                raise ValueError(f"{DETAIL_LABELS[field_name]} must be text")
            value = " ".join(value.split())
            if not value or len(value) > 120:
                raise ValueError(f"{DETAIL_LABELS[field_name]} must contain 1 to 120 characters")
        normalized[field_name] = value

    if estate_type is EstateType.FLAT:
        floor = normalized.get("floor_number")
        total_floors = normalized.get("total_floors")
        if floor is not None and total_floors is not None and floor > total_floors:
            raise ValueError("Floor cannot exceed total floors")
    return normalized


class EstateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=160)
    estate_type: EstateType
    status: EstateStatus = EstateStatus.AVAILABLE
    location: LocationSelection
    asking_price_inr: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=10000)
    details: EstateDetails = Field(default_factory=dict)
    assigned_to: UUID | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Estate title must contain at least two characters")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_details(self):
        object.__setattr__(
            self, "details", validate_estate_details(self.estate_type, self.details)
        )
        return self


class EstateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=2, max_length=160)
    estate_type: EstateType | None = None
    status: EstateStatus | None = None
    location: LocationSelection | None = None
    asking_price_inr: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=10000)
    details: EstateDetails | None = None
    assigned_to: UUID | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Estate title must contain at least two characters")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class EstateRead(BaseModel):
    id: UUID
    team_id: UUID
    assigned_to: UUID | None
    assigned_to_name: str | None
    title: str
    estate_type: EstateType
    status: EstateStatus
    location: LocationSelection
    asking_price_inr: int | None
    description: str | None
    details: EstateDetails
    created_at: datetime
    updated_at: datetime


class EstateAssigneeRead(BaseModel):
    id: UUID
    full_name: str
    role: UserRole


class EstateInterestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID


class EstateInterestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: EstateInterestStatus


class EstateInterestRead(BaseModel):
    id: UUID
    lead_id: UUID
    lead_name: str
    assigned_to: UUID | None
    assigned_to_name: str | None
    status: EstateInterestStatus
    created_at: datetime
    updated_at: datetime


class EstateVisitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    notes: Annotated[str | None, Field(max_length=10000)] = None
    occurred_at: datetime | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class EstateVisitRead(BaseModel):
    id: UUID
    lead_id: UUID
    lead_name: str
    visited_by: UUID
    visited_by_name: str
    occurred_at: datetime
    notes: str | None


class EstatePipelineRead(BaseModel):
    interests: list[EstateInterestRead]
    visits: list[EstateVisitRead]
