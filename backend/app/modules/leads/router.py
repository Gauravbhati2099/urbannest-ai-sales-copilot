from __future__ import annotations

import csv
import io
import os
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from zipfile import BadZipFile, ZipFile
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, status
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.dependencies import (
    CurrentUser,
    DatabaseSession,
    is_team_record_manager,
)
from app.core.normalization import normalize_person_name
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
    LeadAssigneeRead,
    LeadCreate,
    LeadDuplicateCheck,
    LeadRead,
    LeadUpdate,
    PublicLeadCreate,
)
from app.modules.audit.service import record_audit_event

router = APIRouter(prefix="/leads", tags=["leads"])
public_router = APIRouter(prefix="/public/leads", tags=["public leads"])
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
XLSX_MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024


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


def validate_assignment_target(
    session: Session,
    user: User,
    assigned_to: UUID,
    *,
    existing_assignee: User | None = None,
) -> User:
    assignee = get_active_team_member(session, user, assigned_to)
    if assignee is None:
        raise HTTPException(status_code=422, detail="Choose an active team member")
    if user.is_superuser or user.role in {UserRole.OWNER, UserRole.CO_OWNER}:
        return assignee
    if user.role is UserRole.MANAGER:
        if assignee.role is not UserRole.AGENT:
            raise HTTPException(
                status_code=403,
                detail="Managers may assign leads only to active agents",
            )
        if assignee.manager_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Managers may assign leads only to their active agents",
            )
        if existing_assignee is not None and (
            existing_assignee.role in {UserRole.OWNER, UserRole.CO_OWNER}
            or (
                existing_assignee.role is UserRole.MANAGER
                and existing_assignee.id != user.id
            )
        ):
            raise HTTPException(
                status_code=403,
                detail="Only a higher-level user may change this lead's assignment",
            )
        return assignee
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _count_same_name_leads(session: Session, team_id: UUID, full_name: str) -> int:
    candidate_pattern = "%".join(normalize_person_name(full_name).split())
    names = session.scalars(
        select(Lead.full_name).where(
            Lead.team_id == team_id,
            Lead.full_name.ilike(candidate_pattern),
        )
    )
    target = normalize_person_name(full_name).casefold()
    duplicate_count = 0
    for name in names:
        try:
            matches = normalize_person_name(name).casefold() == target
        except ValueError:
            matches = False
        if matches:
            duplicate_count += 1
    return duplicate_count


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


def _normalize_import_headers(headers: list[object]) -> list[str]:
    normalized = [str(header or "").strip().lower() for header in headers]
    while normalized and not normalized[-1]:
        normalized.pop()
    if not normalized or any(not header for header in normalized):
        raise HTTPException(
            status_code=422,
            detail="Every import column must have a header",
        )
    if len(normalized) != len(set(normalized)):
        raise HTTPException(status_code=422, detail="File contains duplicate column names")
    if len(normalized) > len(CSV_COLUMNS):
        raise HTTPException(
            status_code=422,
            detail=f"File may contain at most {len(CSV_COLUMNS)} columns",
        )
    if "full_name" not in normalized:
        raise HTTPException(status_code=422, detail="File must include a full_name column")
    unknown_columns = set(normalized) - CSV_COLUMNS
    if unknown_columns:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported columns: {', '.join(sorted(unknown_columns))}",
        )
    return normalized


def _import_cell_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _collect_import_rows(
    rows: Iterable[tuple[int, Sequence[object]]],
) -> list[tuple[int, list[object]]]:
    collected: list[tuple[int, list[object]]] = []
    try:
        for row_number, row in rows:
            if not any(_import_cell_text(value) for value in row):
                continue
            collected.append((row_number, list(row)))
            if len(collected) > CSV_MAX_ROWS:
                raise HTTPException(
                    status_code=413,
                    detail=f"Import file may contain at most {CSV_MAX_ROWS} data rows",
                )
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail="CSV contains malformed quoting") from exc
    return collected


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
    """List visible leads with optional pagination, search, and field filters."""
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


@router.get("/assignees", response_model=list[LeadAssigneeRead])
def list_lead_assignees(
    current_user: CurrentUser,
    session: DatabaseSession,
) -> list[User]:
    """Return only the active team members this user is permitted to assign."""
    if current_user.is_superuser or current_user.role in {UserRole.OWNER, UserRole.CO_OWNER}:
        roles = None
    elif current_user.role is UserRole.MANAGER:
        roles = {UserRole.AGENT}
    else:
        raise HTTPException(status_code=403, detail="Forbidden")
    statement = select(User).where(
        User.team_id == current_user.team_id,
        User.is_active.is_(True),
    )
    if roles is not None:
        statement = statement.where(User.role.in_(roles))
    if current_user.role is UserRole.MANAGER and not current_user.is_superuser:
        statement = statement.where(User.manager_id == current_user.id)
    return list(session.scalars(statement.order_by(User.full_name, User.email)).all())


@router.get("/duplicates", response_model=LeadDuplicateCheck)
def check_lead_duplicates(
    full_name: Annotated[str, Query(min_length=1, max_length=160)],
    current_user: CurrentUser,
    session: DatabaseSession,
) -> LeadDuplicateCheck:
    """Check for a same-name lead without revealing its contact information."""
    try:
        normalized_name = normalize_person_name(full_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LeadDuplicateCheck(
        duplicate_count=_count_same_name_leads(
            session, current_user.team_id, normalized_name
        )
    )


@router.post("", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: LeadCreate, current_user: CurrentUser, session: DatabaseSession
) -> Lead:
    """Create a lead; agents can only assign new leads to themselves."""
    _validate_budget_range(payload.budget_min_inr, payload.budget_max_inr)
    duplicate_count = _count_same_name_leads(
        session, current_user.team_id, payload.full_name
    )
    if duplicate_count and not payload.allow_duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_lead",
                "message": "A lead with this name already exists",
                "duplicate_count": duplicate_count,
            },
        )
    assigned_to = payload.assigned_to
    if current_user.role is UserRole.AGENT and not current_user.is_superuser:
        if assigned_to is not None and assigned_to != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        assigned_to = current_user.id
    elif assigned_to is None:
        assigned_to = current_user.id
    else:
        validate_assignment_target(session, current_user, assigned_to)

    lead = Lead(
        team_id=current_user.team_id,
        created_by=current_user.id,
        assigned_to=assigned_to,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        phone_country_code=payload.phone_country_code,
        phone_region=payload.phone_region,
        phone_national_number=payload.phone_national_number,
        source=payload.source,
        status=payload.status,
        budget_min_inr=payload.budget_min_inr,
        budget_max_inr=payload.budget_max_inr,
        bhk=payload.bhk,
        preferred_location=payload.preferred_location,
        location=payload.location.model_dump() if payload.location else None,
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
    """Return one lead visible to the authenticated user."""
    return get_accessible_lead(session, current_user, lead_id)


@router.patch("/{lead_id}", response_model=LeadRead)
def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> Lead:
    """Partially update a visible lead; only managers and owners can reassign it."""
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
        "phone_country_code",
        "phone_region",
        "phone_national_number",
        "budget_min_inr",
        "budget_max_inr",
        "bhk",
        "preferred_location",
        "location",
        "notes",
        "assigned_to",
    }
    if set(
        ("phone", "phone_country_code", "phone_region", "phone_national_number")
    ).intersection(payload.model_fields_set):
        for field in (
            "phone",
            "phone_country_code",
            "phone_region",
            "phone_national_number",
        ):
            changes[field] = getattr(payload, field)
    if "location" in payload.model_fields_set:
        changes["location"] = (
            payload.location.model_dump() if payload.location is not None else None
        )
        changes["preferred_location"] = (
            payload.preferred_location if payload.location is not None else None
        )
    elif "preferred_location" in payload.model_fields_set:
        changes["location"] = None
    if any(value is None and key not in nullable_fields for key, value in changes.items()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Required lead fields cannot be null",
        )
    if "assigned_to" in changes:
        existing_assignee = (
            session.get(User, lead.assigned_to) if lead.assigned_to is not None else None
        )
        validate_assignment_target(
            session,
            current_user,
            changes["assigned_to"],
            existing_assignee=existing_assignee,
        )

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
            "location",
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
    """List a lead's activity newest first."""
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
    """Record an activity on a visible lead and mark prior AI scores stale."""
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
    """Import up to 500 CSV or XLSX rows; managers and owners receive per-row errors."""
    if not is_team_record_manager(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    extension = os.path.splitext(file.filename or "")[1].lower()
    if extension not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="Upload a .csv or .xlsx file")
    content = await file.read(CSV_MAX_BYTES + 1)
    await file.close()
    if len(content) > CSV_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Import file exceeds the 2 MiB limit")

    if extension == ".csv":
        try:
            text_content = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="CSV must be UTF-8 encoded") from exc
        try:
            reader = csv.reader(io.StringIO(text_content, newline=""), strict=True)
            raw_headers = next(reader, None)
            if raw_headers is None:
                raise HTTPException(status_code=422, detail="File must include a header row")
            headers = _normalize_import_headers(raw_headers)
            source_rows = _collect_import_rows(enumerate(reader, start=2))
        except csv.Error as exc:
            raise HTTPException(status_code=422, detail="CSV contains malformed quoting") from exc
    else:
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                if "[Content_Types].xml" not in archive.namelist():
                    raise HTTPException(status_code=422, detail="Excel file is not a valid .xlsx workbook")
                uncompressed_size = sum(entry.file_size for entry in archive.infolist())
                if uncompressed_size > XLSX_MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Excel file expands beyond the 20 MiB processing limit",
                    )
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            try:
                worksheet = workbook.active
                if worksheet is None:
                    raise HTTPException(status_code=422, detail="Excel file does not contain a worksheet")
                if worksheet.max_row > CSV_MAX_ROWS + 1:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Import file may contain at most {CSV_MAX_ROWS} data rows",
                    )
                rows = worksheet.iter_rows(values_only=True)
                raw_headers = next(rows, None)
                if raw_headers is None:
                    raise HTTPException(status_code=422, detail="File must include a header row")
                headers = _normalize_import_headers(list(raw_headers))
                source_rows = _collect_import_rows(enumerate(rows, start=2))
            finally:
                workbook.close()
        except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Excel file could not be read; upload a valid .xlsx workbook",
            ) from exc
    if not source_rows:
        raise HTTPException(status_code=422, detail="File must include at least one lead row")

    imported: list[Lead] = []
    errors: list[CSVRowError] = []
    for row_number, raw_row in source_rows:
        cells = [_import_cell_text(value) for value in raw_row]
        if any(cells[len(headers) :]):
            errors.append(
                CSVRowError(
                    row=row_number,
                    message="Row contains values beyond the header columns",
                )
            )
            continue
        normalized_cells = cells[: len(headers)]
        normalized_cells.extend([None] * (len(headers) - len(normalized_cells)))
        row = dict(zip(headers, normalized_cells, strict=True))
        try:
            payload = _parse_csv_row(row)
            _validate_budget_range(payload.budget_min_inr, payload.budget_max_inr)
            assignee_id = payload.assigned_to or current_user.id
            if payload.assigned_to is not None:
                validate_assignment_target(session, current_user, assignee_id)
            imported.append(
                Lead(
                    team_id=current_user.team_id,
                    created_by=current_user.id,
                    assigned_to=assignee_id,
                    full_name=payload.full_name,
                    email=payload.email,
                    phone=payload.phone,
                    phone_country_code=payload.phone_country_code,
                    phone_region=payload.phone_region,
                    phone_national_number=payload.phone_national_number,
                    source=payload.source,
                    status=payload.status,
                    budget_min_inr=payload.budget_min_inr,
                    budget_max_inr=payload.budget_max_inr,
                    bhk=payload.bhk,
                    preferred_location=payload.preferred_location,
                    location=payload.location.model_dump() if payload.location else None,
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
    """Accept an unauthenticated website inquiry for the configured team."""
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
        phone_country_code=payload.phone_country_code,
        phone_region=payload.phone_region,
        phone_national_number=payload.phone_national_number,
        source=LeadSource.WEBSITE,
        status=LeadStatus.NEW,
        budget_min_inr=payload.budget_min_inr,
        budget_max_inr=payload.budget_max_inr,
        bhk=payload.bhk,
        preferred_location=payload.preferred_location,
        location=payload.location.model_dump() if payload.location else None,
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
