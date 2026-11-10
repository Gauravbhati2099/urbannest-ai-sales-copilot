from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser, DatabaseSession
from app.db.models import (
    Activity,
    ActivityType,
    AuditVisibility,
    Lead,
    Task,
    TaskStatus,
    User,
    UserRole,
)
from app.modules.leads.router import get_accessible_lead, get_active_team_member
from app.modules.tasks.schemas import TaskCreate, TaskRead, TaskUpdate
from app.modules.audit.service import record_audit_event

router = APIRouter(prefix="/tasks", tags=["tasks"])
MANAGER_ROLES = {UserRole.OWNER, UserRole.MANAGER}


def accessible_task_statement(user: User):
    statement = (
        select(Task)
        .join(
            Lead,
            and_(Task.lead_id == Lead.id, Task.team_id == Lead.team_id),
        )
        .where(Task.team_id == user.team_id)
    )
    if user.role is UserRole.AGENT:
        statement = statement.where(Lead.assigned_to == user.id)
    return statement


def get_accessible_task(session: Session, user: User, task_id: UUID) -> Task:
    task = session.scalar(accessible_task_statement(user).where(Task.id == task_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if user.role is UserRole.AGENT and task.assigned_to != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.get("", response_model=list[TaskRead])
def list_tasks(
    current_user: CurrentUser,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    due: Literal["today", "overdue"] | None = None,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
) -> list[Task]:
    statement = accessible_task_statement(current_user)
    statement = statement.where(
        Task.status == (status_filter or TaskStatus.OPEN)
    )
    if due is not None:
        if status_filter not in (None, TaskStatus.OPEN):
            raise HTTPException(
                status_code=422,
                detail="Due filters can only be used with open tasks",
            )
        local_now = datetime.now(ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata")))
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        start_utc = day_start.astimezone(timezone.utc)
        end_utc = day_end.astimezone(timezone.utc)
        if due == "today":
            statement = statement.where(Task.due_at >= start_utc, Task.due_at < end_utc)
        else:
            statement = statement.where(Task.due_at < start_utc)
    statement = statement.order_by(Task.due_at.asc())
    return list(session.scalars(statement.limit(limit).offset(offset)).all())


@router.get("/{task_id}", response_model=TaskRead)
def read_task(
    task_id: UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> Task:
    return get_accessible_task(session, current_user, task_id)


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate, current_user: CurrentUser, session: DatabaseSession
) -> Task:
    lead = get_accessible_lead(session, current_user, payload.lead_id)
    assigned_to = (
        payload.assigned_to
        if payload.assigned_to is not None
        else current_user.id
    )
    if current_user.role is UserRole.AGENT and assigned_to != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    get_active_team_member(session, current_user, assigned_to)

    task = Task(
        team_id=current_user.team_id,
        lead_id=lead.id,
        assigned_to=assigned_to,
        created_by=current_user.id,
        title=payload.title,
        description=payload.description,
        due_at=payload.due_at,
    )
    session.add(task)
    session.flush()
    record_audit_event(
        session,
        team_id=task.team_id,
        actor_id=current_user.id,
        lead_id=lead.id,
        entity_type="task",
        entity_id=task.id,
        action="created",
        visibility=AuditVisibility.TEAM,
        summary="A follow-up task was created",
        changes={"due_at": task.due_at.isoformat()},
    )
    session.commit()
    session.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> Task:
    task = get_accessible_task(session, current_user, task_id)
    if (
        current_user.role not in MANAGER_ROLES
        and task.assigned_to != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    previous_assignee = task.assigned_to
    if "assigned_to" in changes:
        if current_user.role not in MANAGER_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        if changes["assigned_to"] is None:
            raise HTTPException(status_code=422, detail="Tasks must have an assignee")
        get_active_team_member(session, current_user, changes["assigned_to"])
        if task.assigned_to != changes["assigned_to"]:
            session.add(
                Activity(
                    team_id=task.team_id,
                    lead_id=task.lead_id,
                    actor_id=current_user.id,
                    type=ActivityType.ASSIGNMENT_CHANGE,
                    body="Follow-up task assignment changed.",
                )
            )
    audit_changes = {}
    if "status" in changes:
        new_status = changes["status"]
        if new_status is None:
            raise HTTPException(status_code=422, detail="Task status cannot be null")
        previous_status = task.status
        task.status = new_status
        if previous_status is not new_status:
            audit_changes["status"] = {
                "from": previous_status.value,
                "to": new_status.value,
            }
        if task.status is TaskStatus.COMPLETED:
            task.completed_at = task.completed_at or datetime.now(timezone.utc)
        else:
            task.completed_at = None
    if "assigned_to" in changes and previous_assignee != changes["assigned_to"]:
        task.assigned_to = changes["assigned_to"]
        audit_changes["assigned_to"] = {
            "from": str(previous_assignee),
            "to": str(task.assigned_to),
        }

    if audit_changes:
        record_audit_event(
            session,
            team_id=task.team_id,
            actor_id=current_user.id,
            lead_id=task.lead_id,
            entity_type="task",
            entity_id=task.id,
            action="updated",
            visibility=AuditVisibility.TEAM,
            summary="A follow-up task was updated",
            changes=audit_changes,
        )

    session.commit()
    session.refresh(task)
    return task
