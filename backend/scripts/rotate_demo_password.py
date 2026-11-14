from __future__ import annotations

import csv
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Team, User
from scripts.seed_demo import DEMO_USERS, TEAM_NAME

CREDENTIALS_CSV = Path(__file__).resolve().parents[1] / "demo_credentials.csv"


@dataclass(frozen=True)
class DemoCredential:
    user_id: UUID
    login_id: str
    role: str
    temporary_password: str


def rotate_demo_password(session: Session) -> list[DemoCredential]:
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

    password_hasher = PasswordHash.recommended()
    credentials = []
    for demo_user in DEMO_USERS:
        user = demo_accounts[demo_user.email]
        temporary_password = secrets.token_urlsafe(24)
        user.password_hash = password_hasher.hash(temporary_password)
        credentials.append(
            DemoCredential(
                user_id=user.id,
                login_id=user.email,
                role=user.role.value,
                temporary_password=temporary_password,
            )
        )
    session.flush()
    return credentials


def _stage_credentials_csv(
    credentials: list[DemoCredential], destination: Path
) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        writer = csv.DictWriter(
            temp_file,
            fieldnames=("user_id", "login_id", "role", "temporary_password"),
        )
        writer.writeheader()
        writer.writerows(
            {
                "user_id": str(credential.user_id),
                "login_id": credential.login_id,
                "role": credential.role,
                "temporary_password": credential.temporary_password,
            }
            for credential in credentials
        )
        temp_file.flush()
        os.fsync(temp_file.fileno())
        return Path(temp_file.name)


def main() -> None:
    from app.db.session import SessionLocal

    staged_csv = None
    committed = False
    try:
        with SessionLocal.begin() as session:
            credentials = rotate_demo_password(session)
            staged_csv = _stage_credentials_csv(credentials, CREDENTIALS_CSV)
        committed = True
    finally:
        if not committed and staged_csv is not None and staged_csv.exists():
            staged_csv.unlink()

    if staged_csv is None:
        raise RuntimeError("Password rotation did not produce a credentials CSV")
    try:
        os.replace(staged_csv, CREDENTIALS_CSV)
    except OSError as error:
        raise RuntimeError(
            "Passwords were reset, but the credentials CSV could not be installed. "
            f"The staged credentials remain at {staged_csv}"
        ) from error

    print(
        f"Rotated passwords for {len(credentials)} seeded demo accounts. "
        f"Local credentials CSV: {CREDENTIALS_CSV}"
    )


if __name__ == "__main__":
    main()
