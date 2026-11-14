from __future__ import annotations

import os
import smtplib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.email import (
    EmailConfigurationError,
    get_smtp_settings,
    send_password_recovery_notification,
)


class SMTPEmailTests(unittest.TestCase):
    def test_recovery_email_uses_starttls_and_only_notifies_owners(self) -> None:
        environment = {
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
            "SMTP_FROM_EMAIL": "crm@example.test",
            "SMTP_USERNAME": "smtp-user",
            "SMTP_PASSWORD": "smtp-password",
            "SMTP_USE_TLS": "true",
            "SMTP_USE_SSL": "false",
        }
        user = SimpleNamespace(
            full_name="Team Member",
            email="member@example.test",
        )
        owners = [
            SimpleNamespace(email="owner@example.test"),
            SimpleNamespace(email="owner@example.test"),
        ]

        with (
            patch.dict(os.environ, environment, clear=True),
            patch("app.core.email.smtplib.SMTP") as smtp_factory,
        ):
            server = smtp_factory.return_value.__enter__.return_value
            server.send_message.return_value = {}
            send_password_recovery_notification(
                user,
                owners,
                get_smtp_settings(),
            )

        smtp_factory.assert_called_once_with(
            "smtp.example.test",
            587,
            timeout=10,
        )
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("smtp-user", "smtp-password")
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "owner@example.test")
        self.assertIn("member@example.test", message.get_content())
        self.assertNotIn("temporary password:", message.get_content().lower())

    def test_plaintext_smtp_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SMTP_HOST": "smtp.example.test",
                "SMTP_FROM_EMAIL": "crm@example.test",
                "SMTP_USE_TLS": "false",
                "SMTP_USE_SSL": "false",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(EmailConfigurationError, "exactly one"):
                get_smtp_settings()

    def test_delivery_errors_are_not_suppressed(self) -> None:
        user = SimpleNamespace(full_name="Team Member", email="member@example.test")
        owner = SimpleNamespace(email="owner@example.test")
        with (
            patch.dict(
                os.environ,
                {
                    "SMTP_HOST": "smtp.example.test",
                    "SMTP_FROM_EMAIL": "crm@example.test",
                    "SMTP_USE_TLS": "true",
                    "SMTP_USE_SSL": "false",
                },
                clear=True,
            ),
            patch("app.core.email.smtplib.SMTP") as smtp_factory,
        ):
            server = smtp_factory.return_value.__enter__.return_value
            server.send_message.side_effect = smtplib.SMTPException("delivery failed")
            with self.assertRaisesRegex(smtplib.SMTPException, "delivery failed"):
                send_password_recovery_notification(
                    user,
                    [owner],
                    get_smtp_settings(),
                )


if __name__ == "__main__":
    unittest.main()
