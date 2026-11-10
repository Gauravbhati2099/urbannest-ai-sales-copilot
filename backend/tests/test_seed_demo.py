import unittest

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from pwdlib import PasswordHash

from app.db.base import Base
from app.db.models import Activity, Lead, Task, Team, User
from scripts.seed_demo import DEMO_USERS, TEAM_NAME, seed_demo_data


class DemoSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(dbapi_connection, _) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_seed_creates_fake_team_users_leads_activities_and_tasks_once(self) -> None:
        emails, demo_password = seed_demo_data(self.session)
        self.session.commit()

        self.assertEqual(len(emails), len(DEMO_USERS))
        self.assertIsNotNone(demo_password)
        self.assertEqual(
            self.session.scalar(
                select(func.count()).select_from(Team).where(Team.name == TEAM_NAME)
            ),
            1,
        )
        self.assertEqual(self.session.scalar(select(func.count()).select_from(User)), 15)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Lead)), 50)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Activity)), 50)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Task)), 50)
        self.assertTrue(demo_password)
        password_hasher = PasswordHash.recommended()
        self.assertTrue(
            all(
                password_hasher.verify(demo_password, user.password_hash)
                for user in self.session.scalars(select(User))
            )
        )

        repeated_emails, repeated_password = seed_demo_data(self.session)
        self.session.commit()

        self.assertEqual(repeated_emails, [])
        self.assertIsNone(repeated_password)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(User)), 15)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Lead)), 50)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Activity)), 50)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Task)), 50)


if __name__ == "__main__":
    unittest.main()
