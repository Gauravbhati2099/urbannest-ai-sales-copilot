from __future__ import annotations

import unittest

from pwdlib import PasswordHash
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Team, User
from scripts.rotate_demo_password import rotate_demo_password
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
            user.email: user.password_hash
            for user in self.session.scalars(select(User)).all()
        }
        password = rotate_demo_password(self.session)
        self.session.commit()

        users = self.session.scalars(select(User)).all()
        self.assertEqual(len(users), len(DEMO_USERS))
        self.assertNotEqual(password, "")
        self.assertTrue(
            all(before[user.email] != user.password_hash for user in users)
        )
        password_hasher = PasswordHash.recommended()
        self.assertTrue(all(password_hasher.verify(password, user.password_hash) for user in users))


if __name__ == "__main__":
    unittest.main()
