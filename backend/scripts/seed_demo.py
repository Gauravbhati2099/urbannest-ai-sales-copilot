from __future__ import annotations

import secrets
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Activity,
    ActivityType,
    Lead,
    LeadSource,
    LeadStatus,
    Task,
    Team,
    TaskStatus,
    User,
    UserRole,
)

TEAM_NAME = "UrbanNest Realty - Demo"
DEMO_USERS = (
    ("owner@demo.urbannest.example.invalid", "Demo Owner", UserRole.OWNER),
    ("manager1@demo.urbannest.example.invalid", "Demo Manager 1", UserRole.MANAGER),
    ("manager2@demo.urbannest.example.invalid", "Demo Manager 2", UserRole.MANAGER),
    *(
        (
            f"agent{number:02d}@demo.urbannest.example.invalid",
            f"Demo Agent {number:02d}",
            UserRole.AGENT,
        )
        for number in range(1, 13)
    ),
)
LOCAL_TIMEZONE = ZoneInfo("Asia/Kolkata")
LOCALITIES = (
    "Baner",
    "Wakad",
    "Hinjawadi",
    "Kharadi",
    "Hadapsar",
    "Aundh",
    "Kothrud",
    "Viman Nagar",
    "Pimpri",
    "Pashan",
)
SOURCES = tuple(LeadSource)
STATUSES = tuple(LeadStatus)


def _local_due_at(days_from_today: int, hour: int) -> datetime:
    local_today = datetime.now(LOCAL_TIMEZONE).date()
    local_due = datetime.combine(
        local_today + timedelta(days=days_from_today),
        time(hour=hour, minute=0),
        tzinfo=LOCAL_TIMEZONE,
    )
    return local_due.astimezone(timezone.utc)


def seed_demo_data(session: Session) -> tuple[list[str], str | None]:
    password_hash = PasswordHash.recommended()

    teams = session.scalars(select(Team).where(Team.name == TEAM_NAME)).all()
    if len(teams) > 1:
        raise RuntimeError(f"Multiple teams named {TEAM_NAME!r}; refusing ambiguous seed")
    team = teams[0] if teams else Team(name=TEAM_NAME)
    if not teams:
        session.add(team)
        session.flush()

    existing_users = {
        email: session.scalar(select(User).where(User.email == email))
        for email, _, _ in DEMO_USERS
    }
    existing_count = sum(user is not None for user in existing_users.values())
    if 0 < existing_count < len(DEMO_USERS):
        raise RuntimeError(
            "Partial demo user set exists; inspect users before continuing the seed"
        )

    demo_password = secrets.token_urlsafe(24) if existing_count == 0 else None
    users_by_email: dict[str, User] = {}
    for email, full_name, role in DEMO_USERS:
        user = existing_users[email]
        if user is None:
            if demo_password is None:
                raise RuntimeError("Demo password was not initialized")
            user = User(
                team_id=team.id,
                full_name=full_name,
                email=email,
                password_hash=password_hash.hash(demo_password),
                role=role,
                is_active=True,
            )
            session.add(user)
        elif user.team_id != team.id or user.role != role:
            raise RuntimeError(
                f"Existing demo user {email!r} has unexpected team or role; refusing to overwrite"
            )
        users_by_email[email] = user

    session.flush()
    owner = users_by_email[DEMO_USERS[0][0]]
    managers = [users_by_email[DEMO_USERS[index][0]] for index in (1, 2)]
    agents = [
        users_by_email[email]
        for email, _, role in DEMO_USERS
        if role is UserRole.AGENT
    ]

    for number in range(1, 51):
        lead_email = f"lead{number:03d}@demo.urbannest.example.invalid"
        lead = session.scalar(
            select(Lead).where(Lead.team_id == team.id, Lead.email == lead_email)
        )
        if lead is None:
            budget_floor = 4_500_000 + (number % 8) * 1_000_000
            lead = Lead(
                team_id=team.id,
                assigned_to=agents[(number - 1) % len(agents)].id,
                created_by=owner.id,
                full_name=f"Demo Lead {number:03d}",
                email=lead_email,
                source=SOURCES[(number - 1) % len(SOURCES)],
                status=STATUSES[(number - 1) % len(STATUSES)],
                budget_min_inr=budget_floor,
                budget_max_inr=budget_floor + 1_500_000,
                bhk=(number % 3) + 1,
                preferred_location=LOCALITIES[(number - 1) % len(LOCALITIES)],
                notes=(
                    f"Synthetic assessment lead {number:03d}; "
                    "all contact details are fictional."
                ),
            )
            session.add(lead)
            session.flush()

        marker = f"Seeded fictional demo activity for lead {number:03d}"
        activity = session.scalar(
            select(Activity).where(
                Activity.team_id == team.id,
                Activity.lead_id == lead.id,
                Activity.body == marker,
            )
        )
        if activity is None:
            session.add(
                Activity(
                    team_id=team.id,
                    lead_id=lead.id,
                    actor_id=agents[(number - 1) % len(agents)].id,
                    type=(
                        ActivityType.SITE_VISIT
                        if number % 5 == 0
                        else ActivityType.CALL
                    ),
                    body=marker,
                    occurred_at=datetime.now(timezone.utc)
                    - timedelta(days=number % 20),
                )
            )

        task_title = f"Demo follow-up {number:03d}"
        task = session.scalar(
            select(Task).where(Task.team_id == team.id, Task.title == task_title)
        )
        if task is None:
            if number % 3 == 1:
                due_at = _local_due_at(-2, 10)
            elif number % 3 == 2:
                due_at = _local_due_at(0, 15)
            else:
                due_at = _local_due_at(2, 11)
            session.add(
                Task(
                    team_id=team.id,
                    lead_id=lead.id,
                    assigned_to=agents[(number - 1) % len(agents)].id,
                    created_by=managers[(number - 1) % len(managers)].id,
                    title=task_title,
                    description="Synthetic reminder for the CRM demo.",
                    due_at=due_at,
                    status=TaskStatus.OPEN,
                )
            )

    session.flush()
    new_emails = [email for email, _, _ in DEMO_USERS] if demo_password else []
    return new_emails, demo_password


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal.begin() as session:
        emails, demo_password = seed_demo_data(session)

    if demo_password:
        print("New demo accounts (all use the shared password shown once below):")
        for email in emails:
            print(email)
        print(f"Shared demo password: {demo_password}")
    else:
        print("Demo data already exists; no accounts or credentials were changed.")


if __name__ == "__main__":
    main()
