from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import bindparam, select
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser, DatabaseSession
from app.db.models import (
    AuditVisibility,
    Estate,
    EstateInterest,
    EstateInterestStatus,
    EstateStatus,
    EstateType,
    EstateVisit,
    Lead,
    User,
    UserRole,
)
from app.modules.audit.service import record_audit_event
from app.modules.leads.router import (
    get_accessible_lead,
    validate_assignment_target,
)
from app.modules.estates.schemas import (
    EstateAssigneeRead,
    EstateCreate,
    EstateInterestCreate,
    EstateInterestRead,
    EstateInterestUpdate,
    EstatePipelineRead,
    EstateRead,
    EstateUpdate,
    EstateVisitCreate,
    EstateVisitRead,
    validate_estate_details,
)

router = APIRouter(prefix="/estates", tags=["estates"])


def accessible_estate_statement(user: User):
    statement = select(Estate).where(Estate.team_id == user.team_id)
    if user.role is UserRole.AGENT:
        statement = statement.where(Estate.assigned_to == user.id)
    return statement


def get_accessible_estate(session: Session, user: User, estate_id: UUID) -> Estate:
    estate = session.scalar(
        accessible_estate_statement(user).where(Estate.id == estate_id)
    )
    if estate is None:
        raise HTTPException(status_code=404, detail="Estate not found")
    return estate


def read_estate(session: Session, estate: Estate, assigned_to_name: str | None = None):
    if estate.assigned_to is not None and assigned_to_name is None:
        assigned_to_name = session.scalar(
            select(User.full_name).where(
                User.id == estate.assigned_to, User.team_id == estate.team_id
            )
        )
    return EstateRead(
        id=estate.id,
        team_id=estate.team_id,
        assigned_to=estate.assigned_to,
        assigned_to_name=assigned_to_name,
        title=estate.title,
        estate_type=estate.estate_type,
        status=estate.status,
        location=estate.location,
        asking_price_inr=estate.asking_price_inr,
        description=estate.description,
        details=estate.details,
        created_at=estate.created_at,
        updated_at=estate.updated_at,
    )


def visible_lead_filter(user: User):
    if user.role is UserRole.AGENT:
        return Lead.assigned_to == user.id
    return True


def audit_estate_change(
    session: Session,
    user: User,
    estate: Estate,
    *,
    action: str,
    summary: str,
    lead_id: UUID | None = None,
    changes: dict[str, object] | None = None,
) -> None:
    record_audit_event(
        session,
        team_id=estate.team_id,
        actor_id=user.id,
        lead_id=lead_id,
        entity_type="estate",
        entity_id=estate.id,
        action=action,
        visibility=AuditVisibility.TEAM,
        summary=summary,
        changes=changes,
    )


@router.get("", response_model=list[EstateRead])
def list_estates(
    current_user: CurrentUser,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    estate_type: EstateType | None = None,
    status_filter: Annotated[EstateStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> list[EstateRead]:
    statement = accessible_estate_statement(current_user).outerjoin(
        User,
        (User.id == Estate.assigned_to) & (User.team_id == Estate.team_id),
    )
    if estate_type is not None:
        statement = statement.where(Estate.estate_type == estate_type)
    if status_filter is not None:
        statement = statement.where(Estate.status == status_filter)
    if q is not None:
        pattern = bindparam("estate_search_pattern", value=f"%{q.strip()}%")
        statement = statement.where(
            Estate.title.ilike(pattern)
            | Estate.location["display_name"].as_string().ilike(pattern)
        )
    rows = session.execute(
        statement.with_only_columns(Estate, User.full_name)
        .order_by(Estate.updated_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [read_estate(session, estate, assigned_to_name) for estate, assigned_to_name in rows]


@router.get("/assignees", response_model=list[EstateAssigneeRead])
def list_estate_assignees(
    current_user: CurrentUser,
    session: DatabaseSession,
) -> list[User]:
    statement = select(User).where(
        User.team_id == current_user.team_id,
        User.is_active.is_(True),
    )
    if current_user.is_superuser or current_user.role in {
        UserRole.OWNER,
        UserRole.CO_OWNER,
    }:
        pass
    elif current_user.role is UserRole.MANAGER:
        statement = statement.where(
            User.role == UserRole.AGENT, User.manager_id == current_user.id
        )
    else:
        statement = statement.where(User.id == current_user.id)
    return list(session.scalars(statement.order_by(User.full_name)).all())


@router.post("", response_model=EstateRead, status_code=status.HTTP_201_CREATED)
def create_estate(
    payload: EstateCreate,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> EstateRead:
    assigned_to = payload.assigned_to
    if current_user.role is UserRole.AGENT and not current_user.is_superuser:
        if assigned_to is not None and assigned_to != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        assigned_to = current_user.id
    elif assigned_to is not None:
        validate_assignment_target(session, current_user, assigned_to)

    estate = Estate(
        team_id=current_user.team_id,
        assigned_to=assigned_to,
        title=payload.title,
        estate_type=payload.estate_type,
        status=payload.status,
        location=payload.location.model_dump(),
        asking_price_inr=payload.asking_price_inr,
        description=payload.description,
        details=payload.details,
    )
    session.add(estate)
    session.flush()
    audit_estate_change(
        session,
        current_user,
        estate,
        action="created",
        summary=f"Estate added: {estate.title}",
        changes={"estate_type": estate.estate_type.value, "status": estate.status.value},
    )
    session.commit()
    session.refresh(estate)
    return read_estate(session, estate)


@router.get("/{estate_id}", response_model=EstateRead)
def read_estate_by_id(
    estate_id: UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> EstateRead:
    return read_estate(session, get_accessible_estate(session, current_user, estate_id))


@router.patch("/{estate_id}", response_model=EstateRead)
def update_estate(
    estate_id: UUID,
    payload: EstateUpdate,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> EstateRead:
    estate = get_accessible_estate(session, current_user, estate_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")

    nullable_fields = {"asking_price_inr", "description", "assigned_to"}
    if any(value is None and key not in nullable_fields for key, value in changes.items()):
        raise HTTPException(status_code=422, detail="Required estate fields cannot be null")

    if (
        "assigned_to" in changes
        and changes["assigned_to"] is not None
        and changes["assigned_to"] != estate.assigned_to
    ):
        if current_user.role is UserRole.AGENT and not current_user.is_superuser:
            if changes["assigned_to"] != current_user.id:
                raise HTTPException(status_code=403, detail="Forbidden")
        else:
            existing_assignee = (
                session.get(User, estate.assigned_to)
                if estate.assigned_to is not None
                else None
            )
            validate_assignment_target(
                session,
                current_user,
                changes["assigned_to"],
                existing_assignee=existing_assignee,
            )

    target_type = changes.get("estate_type", estate.estate_type)
    target_details = changes.get("details", estate.details)
    try:
        changes["details"] = validate_estate_details(target_type, target_details)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    old_values = {key: getattr(estate, key) for key in changes}
    for field, value in changes.items():
        if field == "location" and value is not None:
            value = value.model_dump()
        setattr(estate, field, value)
    changed_fields = [
        key for key in changes if old_values[key] != getattr(estate, key)
    ]
    if changed_fields:
        safe_changes: dict[str, object] = {}
        for field in ("estate_type", "status", "asking_price_inr", "assigned_to"):
            if field not in changed_fields:
                continue
            old_value = old_values[field]
            new_value = getattr(estate, field)
            safe_changes[field] = {
                "from": old_value.value if isinstance(old_value, EstateType | EstateStatus) else str(old_value) if old_value else None,
                "to": new_value.value if isinstance(new_value, EstateType | EstateStatus) else str(new_value) if new_value else None,
            }
        other_changes = set(changed_fields) - set(safe_changes)
        if other_changes:
            safe_changes["changed_fields"] = sorted(other_changes)
        audit_estate_change(
            session,
            current_user,
            estate,
            action="updated",
            summary=f"Estate updated: {estate.title}",
            changes=safe_changes,
        )

    session.commit()
    session.refresh(estate)
    return read_estate(session, estate)


@router.get("/{estate_id}/pipeline", response_model=EstatePipelineRead)
def read_estate_pipeline(
    estate_id: UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> EstatePipelineRead:
    estate = get_accessible_estate(session, current_user, estate_id)
    interest_rows = session.execute(
        select(EstateInterest, Lead.full_name, Lead.assigned_to, User.full_name)
        .join(
            Lead,
            (Lead.id == EstateInterest.lead_id)
            & (Lead.team_id == EstateInterest.team_id),
        )
        .outerjoin(
            User,
            (User.id == Lead.assigned_to) & (User.team_id == Lead.team_id),
        )
        .where(
            EstateInterest.team_id == estate.team_id,
            EstateInterest.estate_id == estate.id,
            visible_lead_filter(current_user),
        )
        .order_by(EstateInterest.updated_at.desc())
    ).all()
    visit_rows = session.execute(
        select(EstateVisit, Lead.full_name, User.full_name)
        .join(
            Lead,
            (Lead.id == EstateVisit.lead_id) & (Lead.team_id == EstateVisit.team_id),
        )
        .join(
            User,
            (User.id == EstateVisit.visited_by) & (User.team_id == EstateVisit.team_id),
        )
        .where(
            EstateVisit.team_id == estate.team_id,
            EstateVisit.estate_id == estate.id,
            visible_lead_filter(current_user),
        )
        .order_by(EstateVisit.occurred_at.desc())
    ).all()
    return EstatePipelineRead(
        interests=[
            EstateInterestRead(
                id=interest.id,
                lead_id=interest.lead_id,
                lead_name=lead_name,
                assigned_to=lead_assigned_to,
                assigned_to_name=assigned_to_name,
                status=interest.status,
                created_at=interest.created_at,
                updated_at=interest.updated_at,
            )
            for interest, lead_name, lead_assigned_to, assigned_to_name in interest_rows
        ],
        visits=[
            EstateVisitRead(
                id=visit.id,
                lead_id=visit.lead_id,
                lead_name=lead_name,
                visited_by=visit.visited_by,
                visited_by_name=visited_by_name,
                occurred_at=visit.occurred_at,
                notes=visit.notes,
            )
            for visit, lead_name, visited_by_name in visit_rows
        ],
    )


@router.post(
    "/{estate_id}/interests",
    response_model=EstateInterestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_estate_interest(
    estate_id: UUID,
    payload: EstateInterestCreate,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> EstateInterestRead:
    estate = get_accessible_estate(session, current_user, estate_id)
    if estate.status in {EstateStatus.SOLD, EstateStatus.WITHDRAWN}:
        raise HTTPException(
            status_code=409, detail="This estate is no longer available for new leads"
        )
    lead = get_accessible_lead(session, current_user, payload.lead_id)
    existing = session.scalar(
        select(EstateInterest).where(
            EstateInterest.team_id == estate.team_id,
            EstateInterest.estate_id == estate.id,
            EstateInterest.lead_id == lead.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Lead is already linked to this estate")
    interest = EstateInterest(
        team_id=estate.team_id,
        estate_id=estate.id,
        lead_id=lead.id,
        created_by=current_user.id,
        status=EstateInterestStatus.INTERESTED,
    )
    session.add(interest)
    audit_estate_change(
        session,
        current_user,
        estate,
        action="lead_linked",
        summary=f"{lead.full_name} linked to {estate.title}",
        lead_id=lead.id,
    )
    session.commit()
    session.refresh(interest)
    return EstateInterestRead(
        id=interest.id,
        lead_id=lead.id,
        lead_name=lead.full_name,
        assigned_to=lead.assigned_to,
        assigned_to_name=lead.assignee.full_name if lead.assignee else None,
        status=interest.status,
        created_at=interest.created_at,
        updated_at=interest.updated_at,
    )


@router.patch(
    "/{estate_id}/interests/{lead_id}",
    response_model=EstateInterestRead,
)
def update_estate_interest(
    estate_id: UUID,
    lead_id: UUID,
    payload: EstateInterestUpdate,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> EstateInterestRead:
    estate = get_accessible_estate(session, current_user, estate_id)
    lead = get_accessible_lead(session, current_user, lead_id)
    interest = session.scalar(
        select(EstateInterest).where(
            EstateInterest.team_id == estate.team_id,
            EstateInterest.estate_id == estate.id,
            EstateInterest.lead_id == lead.id,
        )
    )
    if interest is None:
        raise HTTPException(status_code=404, detail="Estate lead not found")
    old_status = interest.status
    interest.status = payload.status
    if old_status != interest.status:
        audit_estate_change(
            session,
            current_user,
            estate,
            action="lead_stage_changed",
            summary=f"{lead.full_name} moved to {interest.status.value.replace('_', ' ')} for {estate.title}",
            lead_id=lead.id,
            changes={"status": {"from": old_status.value, "to": interest.status.value}},
        )
    session.commit()
    session.refresh(interest)
    return EstateInterestRead(
        id=interest.id,
        lead_id=lead.id,
        lead_name=lead.full_name,
        assigned_to=lead.assigned_to,
        assigned_to_name=lead.assignee.full_name if lead.assignee else None,
        status=interest.status,
        created_at=interest.created_at,
        updated_at=interest.updated_at,
    )


@router.post(
    "/{estate_id}/visits",
    response_model=EstateVisitRead,
    status_code=status.HTTP_201_CREATED,
)
def create_estate_visit(
    estate_id: UUID,
    payload: EstateVisitCreate,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> EstateVisitRead:
    estate = get_accessible_estate(session, current_user, estate_id)
    lead = get_accessible_lead(session, current_user, payload.lead_id)
    interest = session.scalar(
        select(EstateInterest).where(
            EstateInterest.team_id == estate.team_id,
            EstateInterest.estate_id == estate.id,
            EstateInterest.lead_id == lead.id,
        )
    )
    if interest is None:
        raise HTTPException(status_code=404, detail="Link this lead to the estate first")

    visit = EstateVisit(
        team_id=estate.team_id,
        estate_id=estate.id,
        lead_id=lead.id,
        visited_by=current_user.id,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
        notes=payload.notes,
    )
    session.add(visit)
    if interest.status is EstateInterestStatus.INTERESTED:
        interest.status = EstateInterestStatus.SITE_VISIT
    audit_estate_change(
        session,
        current_user,
        estate,
        action="site_visit",
        summary=f"{lead.full_name} visited {estate.title}",
        lead_id=lead.id,
    )
    session.commit()
    session.refresh(visit)
    return EstateVisitRead(
        id=visit.id,
        lead_id=lead.id,
        lead_name=lead.full_name,
        visited_by=current_user.id,
        visited_by_name=current_user.full_name,
        occurred_at=visit.occurred_at,
        notes=visit.notes,
    )
