from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.dependencies import CurrentUser, DatabaseSession
from app.db.models import Lead, LeadStatus, Task, TaskStatus, User, UserRole
from app.modules.dashboard.schemas import DashboardSummary, DashboardTask
from app.modules.tasks.router import accessible_task_statement

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _dashboard_timezone() -> ZoneInfo:
    timezone_name = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard timezone is not configured correctly",
        ) from exc


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    current_user: CurrentUser,
    session: DatabaseSession,
) -> DashboardSummary:
    """Return role-scoped lead totals and open-task due and overdue summaries."""
    timezone_info = _dashboard_timezone()
    now_local = datetime.now(timezone_info)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    today_start_utc = today_start.astimezone(timezone.utc)
    tomorrow_start_utc = tomorrow_start.astimezone(timezone.utc)

    lead_query = select(Lead.status, func.count(Lead.id)).where(
        Lead.team_id == current_user.team_id
    )
    if current_user.role is UserRole.AGENT:
        lead_query = lead_query.where(Lead.assigned_to == current_user.id)
    lead_counts = {
        lead_status.value: 0
        for lead_status in LeadStatus
    }
    for lead_status, count in session.execute(
        lead_query.group_by(Lead.status)
    ).all():
        lead_counts[lead_status.value] = count

    visible_tasks = accessible_task_statement(current_user).where(
        Task.status == TaskStatus.OPEN
    )
    open_tasks = session.scalar(
        select(func.count()).select_from(visible_tasks.subquery())
    ) or 0

    def tasks_in_range(*conditions):
        query = (
            visible_tasks.where(*conditions)
            .join(User, (Task.assigned_to == User.id) & (Task.team_id == User.team_id))
            .add_columns(Lead.full_name, Lead.status, User.full_name)
            .order_by(Task.due_at.asc())
        )
        return [
            DashboardTask(
                id=row[0].id,
                lead_id=row[0].lead_id,
                lead_name=row[1],
                assigned_to_name=row[3],
                lead_status=row[2],
                title=row[0].title,
                due_at=row[0].due_at,
                status=row[0].status,
            )
            for row in session.execute(query).all()
        ]

    due_today = tasks_in_range(
        Task.due_at >= today_start_utc,
        Task.due_at < tomorrow_start_utc,
    )
    overdue = tasks_in_range(Task.due_at < today_start_utc)

    return DashboardSummary(
        timezone=timezone_info.key,
        total_leads=sum(lead_counts.values()),
        pipeline_counts=lead_counts,
        open_tasks=open_tasks,
        due_today_count=len(due_today),
        overdue_count=len(overdue),
        due_today=due_today,
        overdue=overdue,
    )
