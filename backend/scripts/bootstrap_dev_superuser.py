from __future__ import annotations

import os
import re
from dataclasses import dataclass

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Team, User, UserRole

BOOTSTRAP_ENVIRONMENT_KEYS = (
    "DEV_SUPERUSER_EMAIL",
    "DEV_SUPERUSER_PASSWORD",
    "DEV_SUPERUSER_FULL_NAME",
    "DEV_SUPERUSER_TEAM",
)


@dataclass(frozen=True)
class DevSuperuserSettings:
    email: str
    password: str
    full_name: str
    team_name: str


def dev_superuser_settings_from_environment() -> DevSuperuserSettings | None:
    enabled = os.getenv("DEV_SUPERUSER_BOOTSTRAP", "").strip().lower() == "true"
    configured = any(os.getenv(key) for key in BOOTSTRAP_ENVIRONMENT_KEYS)
    if not enabled:
        if configured:
            raise RuntimeError(
                "Set DEV_SUPERUSER_BOOTSTRAP=true to use dev superuser settings"
            )
        return None

    if os.getenv("APP_ENV", "").strip().lower() != "development":
        raise RuntimeError(
            "Dev superuser bootstrap is permitted only when APP_ENV=development"
        )

    values = {
        key: os.getenv(key, "")
        if key == "DEV_SUPERUSER_PASSWORD"
        else os.getenv(key, "").strip()
        for key in BOOTSTRAP_ENVIRONMENT_KEYS
    }
    missing = [key for key, value in values.items() if not value.strip()]
    if missing:
        raise RuntimeError(
            "Dev superuser bootstrap requires: " + ", ".join(missing)
        )
    email = values["DEV_SUPERUSER_EMAIL"].lower()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) is None:
        raise RuntimeError("DEV_SUPERUSER_EMAIL must be a valid email address")
    if len(values["DEV_SUPERUSER_PASSWORD"]) < 12:
        raise RuntimeError("DEV_SUPERUSER_PASSWORD must be at least 12 characters")
    if len(values["DEV_SUPERUSER_FULL_NAME"]) > 160:
        raise RuntimeError("DEV_SUPERUSER_FULL_NAME must be at most 160 characters")
    if len(values["DEV_SUPERUSER_TEAM"]) > 160:
        raise RuntimeError("DEV_SUPERUSER_TEAM must be at most 160 characters")

    return DevSuperuserSettings(
        email=email,
        password=values["DEV_SUPERUSER_PASSWORD"],
        full_name=values["DEV_SUPERUSER_FULL_NAME"],
        team_name=values["DEV_SUPERUSER_TEAM"],
    )


def bootstrap_dev_superuser(
    session: Session, settings: DevSuperuserSettings
) -> bool:
    teams = session.scalars(
        select(Team).where(Team.name == settings.team_name)
    ).all()
    if len(teams) > 1:
        raise RuntimeError("Multiple development teams have the configured name")
    team = teams[0] if teams else Team(name=settings.team_name)
    if not teams:
        session.add(team)
        session.flush()

    user = session.scalar(select(User).where(User.email == settings.email))
    if user is not None:
        if (
            user.team_id != team.id
            or user.role is not UserRole.OWNER
            or not user.is_superuser
        ):
            raise RuntimeError(
                "The configured dev superuser email already belongs to another account"
            )
        return False

    user = User(
        team_id=team.id,
        full_name=settings.full_name,
        email=settings.email,
        password_hash=PasswordHash.recommended().hash(settings.password),
        role=UserRole.OWNER,
        is_superuser=True,
        is_active=True,
        must_change_password=False,
    )
    session.add(user)
    session.flush()
    return True
