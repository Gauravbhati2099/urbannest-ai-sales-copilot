from __future__ import annotations

import secrets

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Team, User
from scripts.seed_demo import DEMO_USERS, TEAM_NAME


def rotate_demo_password(session: Session) -> str:
    expected_users = {email: role for email, _, role in DEMO_USERS}
    users = session.scalars(
        select(User).where(User.email.in_(expected_users))
    ).all()
    if len(users) != len(expected_users):
        raise RuntimeError(
            "The complete seeded demo account set was not found; no passwords changed"
        )

    users_by_email = {user.email: user for user in users}
    if set(users_by_email) != set(expected_users):
        raise RuntimeError(
            "The seeded demo account set was ambiguous; no passwords changed"
        )

    team_ids = {user.team_id for user in users}
    if len(team_ids) != 1:
        raise RuntimeError(
            "Demo accounts do not belong to one team; no passwords changed"
        )
    team_name = session.scalar(
        select(Team.name)
        .join(User, User.team_id == Team.id)
        .where(User.id == users[0].id)
    )
    if team_name != TEAM_NAME:
        raise RuntimeError(
            "The expected UrbanNest demo team was not found; no passwords changed"
        )

    if any(user.role != expected_users[user.email] for user in users):
        raise RuntimeError(
            "A demo account has an unexpected role; no passwords changed"
        )

    new_password = secrets.token_urlsafe(24)
    password_hasher = PasswordHash.recommended()
    for user in users:
        user.password_hash = password_hasher.hash(new_password)
    session.flush()
    return new_password


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal.begin() as session:
        new_password = rotate_demo_password(session)

    print("Rotated passwords for the 15 synthetic UrbanNest demo accounts.")
    print(f"Shared demo password (save it now): {new_password}")


if __name__ == "__main__":
    main()
