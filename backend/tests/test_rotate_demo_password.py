from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from pwdlib import PasswordHash
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Team, User
from scripts.rotate_demo_password import (
    DemoCredential,
    _stage_credentials_csv,
    rotate_demo_password,
)
from scripts.seed_demo import DEMO_USERS, TEAM_NAME, seed_demo_data


class DemoPasswordRotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add(Team(name=TEAM_NAME))
        self.session.flush()
        seed_demo_data(self.session)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_rotation_changes_only_the_expected_demo_password_hashes(self) -> None:
        before = {
            user.id: (user.password_hash, user.email, user.full_name, user.phone)
            for user in self.session.scalars(select(User)).all()
        }
        credentials = rotate_demo_password(self.session)
        self.session.commit()

        users = self.session.scalars(select(User)).all()
        self.assertEqual(len(users), len(DEMO_USERS))
        self.assertEqual(len(credentials), len(DEMO_USERS))
        self.assertEqual(
            len({credential.temporary_password for credential in credentials}),
            len(DEMO_USERS),
        )
        password_hasher = PasswordHash.recommended()
        credentials_by_id = {
            credential.user_id: credential for credential in credentials
        }
        for user in users:
            credential = credentials_by_id[user.id]
            self.assertNotEqual(before[user.id][0], user.password_hash)
            self.assertEqual(
                (user.email, user.full_name, user.phone),
                before[user.id][1:],
            )
            self.assertEqual(credential.login_id, user.email)
            self.assertEqual(credential.role, user.role.value)
            self.assertTrue(
                password_hasher.verify(
                    credential.temporary_password, user.password_hash
                )
            )

    def test_rotation_preserves_legacy_account_identifiers_and_other_demo_data(self) -> None:
        users = self.session.scalars(select(User)).all()
        for demo_user in DEMO_USERS:
            user = next(user for user in users if user.email == demo_user.email)
            user.email = demo_user.legacy_email
            user.full_name = f"Demo {demo_user.role.value}"
            user.phone = None
        self.session.commit()

        credentials = rotate_demo_password(self.session)
        self.session.commit()

        users_by_email = {
            user.email: user for user in self.session.scalars(select(User)).all()
        }
        self.assertEqual(
            set(users_by_email),
            {demo_user.legacy_email for demo_user in DEMO_USERS},
        )
        credentials_by_login = {
            credential.login_id: credential for credential in credentials
        }
        password_hasher = PasswordHash.recommended()
        for demo_user in DEMO_USERS:
            user = users_by_email[demo_user.legacy_email]
            self.assertEqual(user.full_name, f"Demo {demo_user.role.value}")
            self.assertIsNone(user.phone)
            self.assertTrue(
                password_hasher.verify(
                    credentials_by_login[user.email].temporary_password,
                    user.password_hash,
                )
            )

    def test_staged_csv_contains_user_id_login_role_and_password(self) -> None:
        user = self.session.scalars(select(User)).first()
        assert user is not None
        credentials = [
            DemoCredential(
                user_id=user.id,
                login_id=user.email,
                role=user.role.value,
                temporary_password="test-temporary-password",
            )
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "demo_credentials.csv"
            staged_csv = _stage_credentials_csv(credentials, destination)
            try:
                with staged_csv.open(encoding="utf-8", newline="") as csv_file:
                    rows = list(csv.DictReader(csv_file))
            finally:
                staged_csv.unlink(missing_ok=True)

        self.assertEqual(
            rows,
            [
                {
                    "user_id": str(user.id),
                    "login_id": user.email,
                    "role": user.role.value,
                    "temporary_password": "test-temporary-password",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
