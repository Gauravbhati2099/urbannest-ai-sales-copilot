from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

from app.db.models import (
    EstateStatus,
    EstateType,
    LeadSource,
    LeadStatus,
    TaskStatus,
)
from app.modules.estates.schemas import EstateRead
from app.modules.leads.schemas import LeadRead
from app.modules.tasks.schemas import TaskRead


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchLeadsInput(ToolInput):
    q: str | None = Field(default=None, min_length=1, max_length=100)
    status: LeadStatus | None = None
    source: LeadSource | None = None
    location: str | None = Field(default=None, min_length=1, max_length=160)
    budget_min_inr: int | None = Field(default=None, ge=0)
    budget_max_inr: int | None = Field(default=None, ge=0)
    limit: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_budget_range(self) -> SearchLeadsInput:
        if (
            self.budget_min_inr is not None
            and self.budget_max_inr is not None
            and self.budget_min_inr > self.budget_max_inr
        ):
            raise ValueError("Minimum budget must not exceed maximum budget")
        return self


class GetLeadSummaryInput(ToolInput):
    lead_id: UUID


class ListTasksInput(ToolInput):
    status: TaskStatus | None = None
    due: Literal["today", "overdue"] | None = None
    limit: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_due_status(self) -> ListTasksInput:
        if self.due is not None and self.status not in (None, TaskStatus.OPEN):
            raise ValueError("Due filters can only be used with open tasks")
        return self


class SearchEstatesInput(ToolInput):
    q: str | None = Field(default=None, min_length=1, max_length=100)
    estate_type: EstateType | None = None
    status: EstateStatus | None = None
    limit: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0)


class GetEstateDetailsInput(ToolInput):
    estate_id: UUID


class LeadSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    full_name: str
    status: LeadStatus
    source: LeadSource
    budget_min_inr: int | None
    budget_max_inr: int | None
    bhk: int | None
    preferred_location: str | None
    updated_at: datetime


class TaskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    lead_id: UUID
    title: str
    status: TaskStatus
    due_at: datetime
    completed_at: datetime | None


class EstateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    estate_type: EstateType
    status: EstateStatus
    location: str
    asking_price_inr: int | None
    updated_at: datetime


class EstatePropertyFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bedrooms: StrictInt | None = None
    bathrooms: StrictInt | None = None
    built_up_area_sqft: StrictInt | None = None
    floor_number: StrictInt | None = None
    total_floors: StrictInt | None = None
    parking_spaces: StrictInt | None = None
    furnishing: str | None = None
    plot_area_sqft: StrictInt | None = None
    frontage_ft: StrictInt | None = None
    depth_ft: StrictInt | None = None
    zoning: str | None = None
    facing: str | None = None
    floors: StrictInt | None = None
    land_area_acres: StrictInt | StrictFloat | None = None
    water_source: str | None = None
    soil_type: str | None = None


class EstateDetail(EstateSummary):
    property_facts: EstatePropertyFacts


ItemT = TypeVar("ItemT")


class PageResult(BaseModel, Generic[ItemT]):
    model_config = ConfigDict(extra="forbid")

    items: list[ItemT]
    has_more: bool
    next_offset: int | None

    @model_validator(mode="after")
    def validate_next_offset(self) -> PageResult[ItemT]:
        if self.has_more != (self.next_offset is not None):
            raise ValueError("next_offset must be present exactly when has_more is true")
        return self


def build_page(
    rows: Sequence[ItemT], *, limit: int, offset: int
) -> PageResult[ItemT]:
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    if offset < 0:
        raise ValueError("offset must not be negative")

    has_more = len(rows) > limit
    return PageResult(
        items=list(rows[:limit]),
        has_more=has_more,
        next_offset=offset + limit if has_more else None,
    )


def project_lead_summary(lead: LeadRead) -> LeadSummary:
    return LeadSummary(
        id=lead.id,
        full_name=lead.full_name,
        status=lead.status,
        source=lead.source,
        budget_min_inr=lead.budget_min_inr,
        budget_max_inr=lead.budget_max_inr,
        bhk=lead.bhk,
        preferred_location=lead.preferred_location,
        updated_at=lead.updated_at,
    )


def project_task_summary(task: TaskRead) -> TaskSummary:
    return TaskSummary(
        task_id=task.id,
        lead_id=task.lead_id,
        title=task.title,
        status=task.status,
        due_at=task.due_at,
        completed_at=task.completed_at,
    )


def project_estate_summary(estate: EstateRead) -> EstateSummary:
    return EstateSummary(
        id=estate.id,
        title=estate.title,
        estate_type=estate.estate_type,
        status=estate.status,
        location=estate.location.display_name,
        asking_price_inr=estate.asking_price_inr,
        updated_at=estate.updated_at,
    )


def project_estate_detail(estate: EstateRead) -> EstateDetail:
    summary = project_estate_summary(estate)
    allowed_facts = EstatePropertyFacts.model_fields
    property_facts = EstatePropertyFacts.model_validate(
        {key: value for key, value in estate.details.items() if key in allowed_facts}
    )
    return EstateDetail(
        **summary.model_dump(),
        property_facts=property_facts,
    )
