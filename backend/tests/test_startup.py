from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scripts.start import _validate_configuration


class StartupConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "API_V1_PREFIX": "/api/v1",
                "APP_TIMEZONE": "Asia/Kolkata",
                "CORS_ORIGINS": "https://crm.example.com,http://localhost:5173",
                "PORT": "10000",
            },
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

        for target in (
            "scripts.start.get_database_url",
            "scripts.start.get_pool_options",
            "scripts.start.get_auth_settings",
        ):
            mocked = patch(target)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_valid_configuration_returns_server_port(self) -> None:
        self.assertEqual(_validate_configuration(), 10000)

    def test_cors_origin_with_path_is_rejected(self) -> None:
        os.environ["CORS_ORIGINS"] = "https://crm.example.com/login"

        with self.assertRaisesRegex(RuntimeError, "CORS_ORIGINS"):
            _validate_configuration()

    def test_missing_cors_origin_is_rejected(self) -> None:
        os.environ["CORS_ORIGINS"] = ""

        with self.assertRaisesRegex(RuntimeError, "CORS_ORIGINS"):
            _validate_configuration()

    def test_invalid_port_is_rejected(self) -> None:
        os.environ["PORT"] = "0"

        with self.assertRaisesRegex(RuntimeError, "PORT"):
            _validate_configuration()

    def test_invalid_rate_limit_setting_is_rejected(self) -> None:
        os.environ["LOGIN_RATE_LIMIT_PER_EMAIL"] = "not-a-number"

        with self.assertRaisesRegex(RuntimeError, "LOGIN_RATE_LIMIT_PER_EMAIL"):
            _validate_configuration()


if __name__ == "__main__":
    unittest.main()
