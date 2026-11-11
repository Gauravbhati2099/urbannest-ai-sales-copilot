from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.db.models import LeadStatus, TaskStatus


class DashboardTask(BaseModel):
    id: UUID
    lead_id: UUID
    assigned_to: UUID
    lead_name: str
    assigned_to_name: str
    lead_status: LeadStatus
    title: str
    due_at: datetime
    status: TaskStatus


class DashboardSummary(BaseModel):
    timezone: str
    total_leads: int
    pipeline_counts: dict[str, int]
    open_tasks: int
    due_today_count: int
    overdue_count: int
    due_today: list[DashboardTask]
    overdue: list[DashboardTask]
