from __future__ import annotations

import unittest

from pwdlib import PasswordHash
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Activity, Lead, Task, Team, User
from scripts.rotate_demo_password import rotate_demo_password
from scripts.seed_demo import DEMO_USERS, LEAD_NAMES, TEAM_NAME, seed_demo_data


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

    def test_rotation_migrates_legacy_demo_accounts_and_changes_passwords(self) -> None:
        users = self.session.scalars(select(User)).all()
        for demo_user in DEMO_USERS:
            user = next(user for user in users if user.email == demo_user.email)
            user.email = demo_user.legacy_email
            user.full_name = f"Demo {demo_user.role.value}"
            user.phone = None

        leads = self.session.scalars(select(Lead)).all()
        lead_numbers = {
            lead.id: LEAD_NAMES.index(lead.full_name) + 1 for lead in leads
        }
        for lead in leads:
            number = lead_numbers[lead.id]
            lead.full_name = f"Demo Lead {number:03d}"
            lead.email = f"lead{number:03d}@demo.urbannest.example.invalid"
            lead.phone = None
        for activity in self.session.scalars(select(Activity)).all():
            number = lead_numbers[activity.lead_id]
            activity.body = f"Seeded fictional demo activity for lead {number:03d}"
        for task in self.session.scalars(select(Task)).all():
            number = lead_numbers[task.lead_id]
            task.title = f"Demo follow-up {number:03d}"
            task.description = "Synthetic reminder for the CRM demo."
        self.session.commit()

        password = rotate_demo_password(self.session)
        self.session.commit()

        users_by_email = {
            user.email: user for user in self.session.scalars(select(User)).all()
        }
        self.assertEqual(set(users_by_email), {demo_user.email for demo_user in DEMO_USERS})
        password_hasher = PasswordHash.recommended()
        for demo_user in DEMO_USERS:
            user = users_by_email[demo_user.email]
            self.assertEqual(user.full_name, demo_user.full_name)
            self.assertEqual(user.phone, demo_user.phone)
            self.assertTrue(password_hasher.verify(password, user.password_hash))
        refreshed_leads = self.session.scalars(select(Lead)).all()
        self.assertEqual({lead.full_name for lead in refreshed_leads}, set(LEAD_NAMES))
        self.assertEqual(len(refreshed_leads), 50)
        self.assertTrue(
            all(
                lead.email is not None
                and lead.email.endswith("@demo.urbannest.example.invalid")
                and lead.phone is not None
                for lead in refreshed_leads
            )
        )
        refreshed_activities = self.session.scalars(select(Activity)).all()
        self.assertEqual(len(refreshed_activities), 50)
        self.assertTrue(
            all(
                activity.body.startswith("Synthetic demo activity ")
                for activity in refreshed_activities
            )
        )
        refreshed_tasks = self.session.scalars(select(Task)).all()
        self.assertEqual(len(refreshed_tasks), 50)
        self.assertTrue(
            all(
                not task.title.startswith("Demo follow-up ")
                and task.description is not None
                and task.description.startswith("Synthetic demo follow-up: ")
                for task in refreshed_tasks
            )
        )


if __name__ == "__main__":
    unittest.main()
