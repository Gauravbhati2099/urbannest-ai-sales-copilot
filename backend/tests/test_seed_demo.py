import unittest
from uuid import UUID

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from pwdlib import PasswordHash

from app.db.base import Base
from app.db.models import Activity, Lead, Task, Team, User, UserRole
from scripts.seed_demo import DEMO_USERS, LEAD_NAMES, TEAM_NAME, seed_demo_data


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
        users = self.session.scalars(select(User)).all()
        self.assertEqual(
            {user.role for user in users},
            {UserRole.OWNER, UserRole.MANAGER, UserRole.AGENT},
        )
        self.assertEqual(sum(user.role is UserRole.OWNER for user in users), 1)
        self.assertEqual(sum(user.role is UserRole.MANAGER for user in users), 2)
        self.assertEqual(sum(user.role is UserRole.AGENT for user in users), 12)
        self.assertTrue(
            all(
                user.full_name != "Demo Owner"
                and "@" in user.email
                and user.email.endswith("@demo.urbannest.example.invalid")
                and user.phone is not None
                and user.phone.startswith("+1 (202) 555-01")
                for user in users
            )
        )
        leads = self.session.scalars(select(Lead)).all()
        self.assertEqual({lead.full_name for lead in leads}, set(LEAD_NAMES))
        self.assertTrue(
            all(
                lead.email is not None
                and lead.email.endswith("@demo.urbannest.example.invalid")
                and lead.phone is not None
                and lead.notes is not None
                and "Synthetic demo inquiry" in lead.notes
                for lead in leads
            )
        )
        activities = self.session.scalars(select(Activity)).all()
        self.assertEqual(
            len({activity.body for activity in activities}),
            50,
        )
        self.assertTrue(
            all(activity.body.startswith("Synthetic demo ") for activity in activities)
        )
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

    def test_seed_upgrades_legacy_demo_records_without_duplicating_them(self) -> None:
        seed_demo_data(self.session)
        self.session.flush()
        password_hashes = {
            user.email: user.password_hash
            for user in self.session.scalars(select(User)).all()
        }

        for demo_user in DEMO_USERS:
            user = self.session.scalar(
                select(User).where(User.email == demo_user.email)
            )
            assert user is not None
            user.email = demo_user.legacy_email
            user.full_name = "Demo User"
            user.phone = None

        leads = self.session.scalars(select(Lead)).all()
        activities = self.session.scalars(select(Activity)).all()
        lead_numbers: dict[UUID, int] = {}
        for lead in leads:
            number = LEAD_NAMES.index(lead.full_name) + 1
            lead_numbers[lead.id] = number
            lead.email = f"lead{number:03d}@demo.urbannest.example.invalid"
            lead.full_name = f"Demo Lead {number:03d}"
            lead.phone = None
        for activity in activities:
            number = lead_numbers[activity.lead_id]
            activity.body = f"Seeded fictional demo activity for lead {number:03d}"
        for task in self.session.scalars(select(Task)).all():
            number = lead_numbers[task.lead_id]
            task.title = f"Demo follow-up {number:03d}"
        self.session.commit()

        _, demo_password = seed_demo_data(self.session)
        self.session.commit()

        self.assertIsNone(demo_password)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(User)), 15)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Lead)), 50)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Activity)), 50)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(Task)), 50)
        for demo_user in DEMO_USERS:
            user = self.session.scalar(
                select(User).where(User.email == demo_user.email)
            )
            self.assertIsNotNone(user)
            self.assertEqual(user.full_name, demo_user.full_name)
            self.assertEqual(user.phone, demo_user.phone)
            self.assertEqual(user.password_hash, password_hashes[demo_user.email])


if __name__ == "__main__":
    unittest.main()
