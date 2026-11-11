from __future__ import annotations

import secrets

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Team, User
from scripts.seed_demo import DEMO_USERS, TEAM_NAME, seed_demo_data


def rotate_demo_password(session: Session) -> str:
    expected_users = {
        email: demo_user
        for demo_user in DEMO_USERS
        for email in (demo_user.legacy_email, demo_user.email)
    }
    users = session.scalars(
        select(User).where(User.email.in_(expected_users))
    ).all()
    users_by_email = {user.email: user for user in users}
    demo_accounts: dict[str, User] = {}
    seen_user_ids = set()
    for demo_user in DEMO_USERS:
        matches = [
            user
            for email in (demo_user.legacy_email, demo_user.email)
            if (user := users_by_email.get(email)) is not None
        ]
        if len(matches) != 1 or matches[0].id in seen_user_ids:
            raise RuntimeError(
                "The complete, unambiguous seeded demo account set was not found; "
                "no passwords changed"
            )
        user = matches[0]
        if user.role != demo_user.role:
            raise RuntimeError(
                f"Demo account {user.email!r} has an unexpected role; "
                "no passwords changed"
            )
        demo_accounts[demo_user.email] = user
        seen_user_ids.add(user.id)

    if len(users) != len(DEMO_USERS):
        raise RuntimeError(
            "The complete seeded demo account set was not found; no passwords changed"
        )

    team_ids = {user.team_id for user in demo_accounts.values()}
    if len(team_ids) != 1:
        raise RuntimeError(
            "Demo accounts do not belong to one team; no passwords changed"
        )
    team_name = session.scalar(
        select(Team.name)
        .join(User, User.team_id == Team.id)
        .where(User.id == next(iter(demo_accounts.values())).id)
    )
    if team_name != TEAM_NAME:
        raise RuntimeError(
            "The expected UrbanNest demo team was not found; no passwords changed"
        )

    _, seeded_password = seed_demo_data(session)
    if seeded_password is not None:
        raise RuntimeError(
            "Demo data refresh unexpectedly created accounts; no passwords changed"
        )

    new_password = secrets.token_urlsafe(24)
    password_hasher = PasswordHash.recommended()
    for demo_user in DEMO_USERS:
        user = demo_accounts[demo_user.email]
        user.email = demo_user.email
        user.full_name = demo_user.full_name
        user.phone = demo_user.phone
        user.password_hash = password_hasher.hash(new_password)
    session.flush()
    return new_password


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal.begin() as session:
        new_password = rotate_demo_password(session)

    print(
        "Updated synthetic demo account details and rotated passwords "
        "for all 15 accounts; refreshed leads, activity, and follow-ups."
    )
    for demo_user in DEMO_USERS:
        print(f"{demo_user.full_name} ({demo_user.role.value}): {demo_user.email}")
    print(f"Shared demo password (save it now): {new_password}")


if __name__ == "__main__":
    main()
