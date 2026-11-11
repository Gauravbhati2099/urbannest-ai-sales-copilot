from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from pwdlib import PasswordHash
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Team, User, UserRole
from scripts.bootstrap_dev_superuser import (
    bootstrap_dev_superuser,
    dev_superuser_settings_from_environment,
)


class DevSuperuserBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_bootstrap_is_opt_in_and_requires_development_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(dev_superuser_settings_from_environment())

        with patch.dict(
            os.environ,
            {
                "DEV_SUPERUSER_BOOTSTRAP": "true",
                "APP_ENV": "production",
                "DEV_SUPERUSER_EMAIL": "root@example.test",
                "DEV_SUPERUSER_PASSWORD": "safe-development-password",
                "DEV_SUPERUSER_FULL_NAME": "Development Owner",
                "DEV_SUPERUSER_TEAM": "Development Team",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "APP_ENV=development"):
                dev_superuser_settings_from_environment()

    def test_bootstrap_creates_idempotent_superuser_for_configured_team(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEV_SUPERUSER_BOOTSTRAP": "true",
                "APP_ENV": "development",
                "DEV_SUPERUSER_EMAIL": " Root@Example.Test ",
                "DEV_SUPERUSER_PASSWORD": "safe-development-password",
                "DEV_SUPERUSER_FULL_NAME": "Development Owner",
                "DEV_SUPERUSER_TEAM": "Development Team",
            },
            clear=True,
        ):
            settings = dev_superuser_settings_from_environment()
        assert settings is not None

        self.assertTrue(bootstrap_dev_superuser(self.session, settings))
        self.session.commit()
        self.assertFalse(bootstrap_dev_superuser(self.session, settings))
        self.session.commit()

        user = self.session.scalar(
            select(User).where(User.email == "root@example.test")
        )
        self.assertIsNotNone(user)
        assert user is not None
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.role, UserRole.OWNER)
        self.assertEqual(user.full_name, "Development Owner")
        self.assertTrue(
            PasswordHash.recommended().verify(
                settings.password, user.password_hash
            )
        )
        self.assertEqual(
            self.session.scalar(select(Team.name).where(Team.id == user.team_id)),
            "Development Team",
        )
        self.assertEqual(self.session.scalar(select(User.id).where(User.email == settings.email)), user.id)


if __name__ == "__main__":
    unittest.main()
