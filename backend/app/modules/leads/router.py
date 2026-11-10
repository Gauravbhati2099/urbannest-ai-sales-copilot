from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser, DatabaseSession
from app.core.rate_limit import client_address, enforce_rate_limits, rate_limit_setting
from app.db.models import (
    Activity,
    ActivityType,
    AuditVisibility,
    Lead,
    LeadScore,
    LeadSource,
    LeadStatus,
    Team,
    User,
    UserRole,
)
from app.modules.leads.schemas import (
    ActivityCreate,
    ActivityRead,
    CSVImportResult,
    CSVRowError,
    LeadCreate,
    LeadRead,
    LeadUpdate,
    PublicLeadCreate,
)
from app.modules.audit.service import record_audit_event

router = APIRouter(prefix="/leads", tags=["leads"])
public_router = APIRouter(prefix="/public/leads", tags=["public leads"])
MANAGER_ROLES = {UserRole.OWNER, UserRole.MANAGER}
CSV_COLUMNS = {
    "full_name",
    "email",
    "phone",
    "source",
    "status",
    "budget_min_inr",
    "budget_max_inr",
    "bhk",
    "preferred_location",
    "notes",
    "assigned_to",
}
CSV_MAX_BYTES = 2 * 1024 * 1024
CSV_MAX_ROWS = 500


def accessible_lead_statement(user: User):
    statement = select(Lead).where(Lead.team_id == user.team_id)
    if user.role is UserRole.AGENT:
        statement = statement.where(Lead.assigned_to == user.id)
    return statement


def get_accessible_lead(session: Session, user: User, lead_id: UUID) -> Lead:
    lead = session.scalar(accessible_lead_statement(user).where(Lead.id == lead_id))
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return lead


def get_active_team_member(
    session: Session, user: User, assigned_to: UUID | None
) -> User | None:
    if assigned_to is None:
        return None
    assignee = session.scalar(
        select(User).where(
            User.id == assigned_to,
            User.team_id == user.team_id,
            User.is_active.is_(True),
        )
    )
    if assignee is None:
        raise HTTPException(
            status_code=422,
            detail="Assignee must be an active user in your team",
        )
    return assignee


def _validate_budget_range(minimum: int | None, maximum: int | None) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        raise HTTPException(
            status_code=422,
            detail="Minimum budget must not exceed maximum budget",
        )


def _csv_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_csv_row(row: dict[str, str | None]) -> LeadCreate:
    normalized = {key.strip().lower(): value for key, value in row.items() if key}
    unknown_columns = set(normalized) - CSV_COLUMNS
    if unknown_columns:
        raise ValueError(f"Unknown CSV columns: {', '.join(sorted(unknown_columns))}")
    if not _csv_value(normalized.get("full_name")):
        raise ValueError("full_name is required")

    def parse_integer(column: str, minimum: int | None = None) -> int | None:
        value = _csv_value(normalized.get(column))
        if value is None:
            return None
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{column} must be a whole number") from exc
        if minimum is not None and parsed < minimum:
            raise ValueError(f"{column} must be at least {minimum}")
        return parsed

    email = _csv_value(normalized.get("email"))
    phone = _csv_value(normalized.get("phone"))
    notes = _csv_value(normalized.get("notes"))
    return LeadCreate(
        full_name=_csv_value(normalized.get("full_name")),
        email=email,
        phone=phone,
        source=_csv_value(normalized.get("source")) or LeadSource.CSV_IMPORT,
        status=_csv_value(normalized.get("status")) or LeadStatus.NEW,
        budget_min_inr=parse_integer("budget_min_inr", 0),
        budget_max_inr=parse_integer("budget_max_inr", 0),
        bhk=parse_integer("bhk", 1),
        preferred_location=_csv_value(normalized.get("preferred_location")),
        notes=notes,
        assigned_to=_parse_assignee(normalized.get("assigned_to")),
    )


def _parse_assignee(value: str | None) -> UUID | None:
    normalized = _csv_value(value)
    if normalized is None:
        return None
    try:
        return UUID(normalized)
    except ValueError as exc:
        raise ValueError("assigned_to must be a valid user ID") from exc


@router.get("", response_model=list[LeadRead])
def list_leads(
    current_user: CurrentUser,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[LeadStatus | None, Query(alias="status")] = None,
    source: LeadSource | None = None,
    assigned_to: UUID | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    location: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    budget_min_inr: Annotated[int | None, Query(ge=0)] = None,
    budget_max_inr: Annotated[int | None, Query(ge=0)] = None,
) -> list[Lead]:
    statement = accessible_lead_statement(current_user)
    if status_filter is not None:
        statement = statement.where(Lead.status == status_filter)
    if source is not None:
        statement = statement.where(Lead.source == source)
    if assigned_to is not None:
        if current_user.role is UserRole.AGENT and assigned_to != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        statement = statement.where(Lead.assigned_to == assigned_to)
    if q is not None:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Lead.full_name.ilike(pattern),
                Lead.email.ilike(pattern),
                Lead.phone.ilike(pattern),
                Lead.preferred_location.ilike(pattern),
            )
        )
    if location is not None:
        statement = statement.where(Lead.preferred_location.ilike(f"%{location.strip()}%"))
    if budget_min_inr is not None:
        statement = statement.where(
            or_(
                Lead.budget_max_inr.is_(None),
                Lead.budget_max_inr >= budget_min_inr,
            )
        )
    if budget_max_inr is not None:
        statement = statement.where(
            or_(
                Lead.budget_min_inr.is_(None),
                Lead.budget_min_inr <= budget_max_inr,
            )
        )
    if (
        budget_min_inr is not None
        and budget_max_inr is not None
        and budget_min_inr > budget_max_inr
    ):
        raise HTTPException(
            status_code=422,
            detail="Minimum budget filter must not exceed maximum budget filter",
        )
    statement = statement.order_by(Lead.created_at.desc())
    return list(session.scalars(statement.limit(limit).offset(offset)).all())


@router.post("", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: LeadCreate, current_user: CurrentUser, session: DatabaseSession
) -> Lead:
    _validate_budget_range(payload.budget_min_inr, payload.budget_max_inr)
    assigned_to = payload.assigned_to
    if current_user.role is UserRole.AGENT:
        if assigned_to is not None and assigned_to != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        assigned_to = current_user.id
    elif assigned_to is not None:
        get_active_team_member(session, current_user, assigned_to)

    lead = Lead(
        team_id=current_user.team_id,
        created_by=current_user.id,
        assigned_to=assigned_to,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        source=payload.source,
        status=payload.status,
        budget_min_inr=payload.budget_min_inr,
        budget_max_inr=payload.budget_max_inr,
        bhk=payload.bhk,
        preferred_location=payload.preferred_location,
        notes=payload.notes,
    )
    session.add(lead)
    session.flush()
    record_audit_event(
        session,
        team_id=lead.team_id,
        actor_id=current_user.id,
        lead_id=lead.id,
        entity_type="lead",
        entity_id=lead.id,
        action="created",
        visibility=AuditVisibility.TEAM,
        summary="A new lead was added",
        changes={"source": lead.source.value, "status": lead.status.value},
    )
    session.commit()
    session.refresh(lead)
    return lead


@router.get("/{lead_id}", response_model=LeadRead)
def read_lead(lead_id: UUID, current_user: CurrentUser, session: DatabaseSession) -> Lead:
    return get_accessible_lead(session, current_user, lead_id)


@router.patch("/{lead_id}", response_model=LeadRead)
def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> Lead:
    lead = get_accessible_lead(session, current_user, lead_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one field to update",
        )

    nullable_fields = {
        "email",
        "phone",
        "budget_min_inr",
        "budget_max_inr",
        "bhk",
        "preferred_location",
        "notes",
        "assigned_to",
    }
    if any(value is None and key not in nullable_fields for key, value in changes.items()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Required lead fields cannot be null",
        )
    if "assigned_to" in changes:
        if current_user.role not in MANAGER_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        get_active_team_member(session, current_user, changes["assigned_to"])

    new_minimum = changes.get("budget_min_inr", lead.budget_min_inr)
    new_maximum = changes.get("budget_max_inr", lead.budget_max_inr)
    _validate_budget_range(new_minimum, new_maximum)

    old_status = lead.status
    old_assignee = lead.assigned_to
    before = {key: getattr(lead, key) for key in changes}
    for field, value in changes.items():
        setattr(lead, field, value)

    if old_status != lead.status:
        session.add(
            Activity(
                team_id=lead.team_id,
                lead_id=lead.id,
                actor_id=current_user.id,
                type=ActivityType.STATUS_CHANGE,
                body=f"Status changed from {old_status.value} to {lead.status.value}.",
            )
        )
    if old_assignee != lead.assigned_to:
        session.add(
            Activity(
                team_id=lead.team_id,
                lead_id=lead.id,
                actor_id=current_user.id,
                type=ActivityType.ASSIGNMENT_CHANGE,
                body="Lead assignment changed.",
            )
        )
    if set(changes).intersection(
        {
            "status",
            "source",
            "budget_min_inr",
            "budget_max_inr",
            "bhk",
            "preferred_location",
            "notes",
        }
    ):
        session.execute(
            update(LeadScore)
            .where(
                LeadScore.team_id == lead.team_id,
                LeadScore.lead_id == lead.id,
                LeadScore.is_stale.is_(False),
            )
            .values(is_stale=True)
        )

    safe_change_fields = {
        "status",
        "assigned_to",
        "source",
        "budget_min_inr",
        "budget_max_inr",
        "bhk",
        "preferred_location",
    }
    changed_fields = [
        field for field in changes if before[field] != getattr(lead, field)
    ]
    audit_changes = {}
    for field in safe_change_fields.intersection(changed_fields):
        old_value = before.get(field)
        new_value = getattr(lead, field)
        if isinstance(old_value, (LeadStatus, LeadSource)):
            old_value = old_value.value
        elif isinstance(old_value, UUID):
            old_value = str(old_value)
        if isinstance(new_value, (LeadStatus, LeadSource)):
            new_value = new_value.value
        elif isinstance(new_value, UUID):
            new_value = str(new_value)
        audit_changes[field] = {"from": old_value, "to": new_value}
    non_value_fields = set(changed_fields) - safe_change_fields
    if non_value_fields:
        audit_changes["changed_fields"] = sorted(non_value_fields)
    if changed_fields:
        record_audit_event(
            session,
            team_id=lead.team_id,
            actor_id=current_user.id,
            lead_id=lead.id,
            entity_type="lead",
            entity_id=lead.id,
            action="updated",
            visibility=AuditVisibility.TEAM,
            summary="Lead details were updated",
            changes=audit_changes,
        )

    session.commit()
    session.refresh(lead)
    return lead


@router.get("/{lead_id}/activities", response_model=list[ActivityRead])
def list_activities(
    lead_id: UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Activity]:
    lead = get_accessible_lead(session, current_user, lead_id)
    statement = (
        select(Activity)
        .where(Activity.team_id == lead.team_id, Activity.lead_id == lead.id)
        .order_by(Activity.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement).all())


@router.post(
    "/{lead_id}/activities",
    response_model=ActivityRead,
    status_code=status.HTTP_201_CREATED,
)
def create_activity(
    lead_id: UUID,
    payload: ActivityCreate,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> Activity:
    lead = get_accessible_lead(session, current_user, lead_id)
    activity = Activity(
        team_id=lead.team_id,
        lead_id=lead.id,
        actor_id=current_user.id,
        type=payload.type,
        body=payload.body,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
    )
    session.add(activity)
    record_audit_event(
        session,
        team_id=lead.team_id,
        actor_id=current_user.id,
        lead_id=lead.id,
        entity_type="lead",
        entity_id=lead.id,
        action="activity_recorded",
        visibility=AuditVisibility.TEAM,
        summary="A lead activity was recorded",
        changes={"activity_type": payload.type.value},
    )
    session.execute(
        update(LeadScore)
        .where(
            LeadScore.team_id == lead.team_id,
            LeadScore.lead_id == lead.id,
            LeadScore.is_stale.is_(False),
        )
        .values(is_stale=True)
    )
    session.commit()
    session.refresh(activity)
    return activity


@router.post(
    "/import",
    response_model=CSVImportResult,
    status_code=status.HTTP_200_OK,
)
async def import_leads_csv(
    file: UploadFile,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> CSVImportResult:
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if file.content_type not in {"text/csv", "application/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=415, detail="Upload a CSV file")
    content = await file.read(CSV_MAX_BYTES + 1)
    await file.close()
    if len(content) > CSV_MAX_BYTES:
        raise HTTPException(status_code=413, detail="CSV file exceeds the 2 MB limit")
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text_content, newline=""))
    if not reader.fieldnames or "full_name" not in {
        column.strip().lower() for column in reader.fieldnames if column
    }:
        raise HTTPException(status_code=422, detail="CSV must include a full_name column")
    normalized_headers = [
        column.strip().lower() for column in reader.fieldnames if column
    ]
    if len(normalized_headers) != len(set(normalized_headers)):
        raise HTTPException(status_code=422, detail="CSV contains duplicate column names")

    imported: list[Lead] = []
    errors: list[CSVRowError] = []
    for row_number, row in enumerate(reader, start=2):
        if row_number > CSV_MAX_ROWS + 1:
            raise HTTPException(
                status_code=413,
                detail=f"CSV may contain at most {CSV_MAX_ROWS} data rows",
            )
        try:
            payload = _parse_csv_row(row)
            _validate_budget_range(payload.budget_min_inr, payload.budget_max_inr)
            assignee_id = payload.assigned_to or (
                current_user.id if current_user.role is UserRole.AGENT else None
            )
            if assignee_id is not None:
                get_active_team_member(session, current_user, assignee_id)
            imported.append(
                Lead(
                    team_id=current_user.team_id,
                    created_by=current_user.id,
                    assigned_to=assignee_id,
                    full_name=payload.full_name,
                    email=payload.email,
                    phone=payload.phone,
                    source=LeadSource.CSV_IMPORT,
                    status=payload.status,
                    budget_min_inr=payload.budget_min_inr,
                    budget_max_inr=payload.budget_max_inr,
                    bhk=payload.bhk,
                    preferred_location=payload.preferred_location,
                    notes=payload.notes,
                )
            )
        except ValidationError as exc:
            messages = [
                error["msg"]
                for error in exc.errors(include_input=False, include_url=False)
            ]
            errors.append(
                CSVRowError(
                    row=row_number,
                    message="; ".join(messages) or "Row failed validation",
                )
            )
        except (ValueError, TypeError) as exc:
            errors.append(CSVRowError(row=row_number, message=str(exc)))
        except HTTPException as exc:
            errors.append(CSVRowError(row=row_number, message=str(exc.detail)))

    if imported:
        session.add_all(imported)
        session.flush()
        record_audit_event(
            session,
            team_id=current_user.team_id,
            actor_id=current_user.id,
            lead_id=None,
            entity_type="team",
            entity_id=None,
            action="lead_imported",
            visibility=AuditVisibility.TEAM,
            summary=f"{len(imported)} leads were imported",
            changes={"created_count": len(imported)},
        )
        session.commit()
        for lead in imported:
            session.refresh(lead)
    else:
        session.rollback()
    return CSVImportResult(
        created_count=len(imported),
        rejected_count=len(errors),
        created_lead_ids=[lead.id for lead in imported],
        errors=errors,
    )


@public_router.post("", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
def create_public_lead(
    payload: PublicLeadCreate,
    request: Request,
    session: DatabaseSession,
) -> Lead:
    enforce_rate_limits(
        session,
        limits=(
            (
                "public_lead_ip",
                client_address(request),
                rate_limit_setting("PUBLIC_LEAD_RATE_LIMIT", 10),
            ),
        ),
        window_seconds=rate_limit_setting(
            "PUBLIC_LEAD_RATE_WINDOW_SECONDS",
            600,
        ),
    )
    raw_team_id = os.getenv("PUBLIC_LEAD_TEAM_ID", "").strip()
    try:
        team_id = UUID(raw_team_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public lead intake is not configured",
        ) from exc

    team = session.scalar(select(Team).where(Team.id == team_id))
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public lead intake is not configured",
        )
    _validate_budget_range(payload.budget_min_inr, payload.budget_max_inr)
    lead = Lead(
        team_id=team.id,
        created_by=None,
        assigned_to=None,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        source=LeadSource.WEBSITE,
        status=LeadStatus.NEW,
        budget_min_inr=payload.budget_min_inr,
        budget_max_inr=payload.budget_max_inr,
        bhk=payload.bhk,
        preferred_location=payload.preferred_location,
    )
    session.add(lead)
    session.flush()
    session.add(
        Activity(
            team_id=team.id,
            lead_id=lead.id,
            actor_id=None,
            type=ActivityType.NOTE,
            body="New inquiry submitted through the public website form.",
        )
    )
    record_audit_event(
        session,
        team_id=team.id,
        actor_id=None,
        lead_id=None,
        entity_type="team",
        entity_id=None,
        action="public_lead_received",
        visibility=AuditVisibility.TEAM,
        summary="A new website inquiry was received",
    )
    session.commit()
    session.refresh(lead)
    return lead
