from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr

from app.db.models import User


class EmailConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    from_email: str
    username: str | None
    password: str | None
    use_tls: bool
    use_ssl: bool
    timeout: float


def get_smtp_settings() -> SMTPSettings:
    host = os.getenv("SMTP_HOST", "").strip()
    from_email = os.getenv("SMTP_FROM_EMAIL", "").strip()
    if not host or not from_email or "\r" in from_email or "\n" in from_email:
        raise EmailConfigurationError(
            "SMTP_HOST and a valid SMTP_FROM_EMAIL must be configured"
        )
    parsed_from_email = parseaddr(from_email)[1]
    if not parsed_from_email or "@" not in parsed_from_email:
        raise EmailConfigurationError("SMTP_FROM_EMAIL must be a valid email address")

    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        timeout = float(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
    except ValueError as exc:
        raise EmailConfigurationError(
            "SMTP_PORT and SMTP_TIMEOUT_SECONDS must be numeric"
        ) from exc
    if not 1 <= port <= 65535 or not 1 <= timeout <= 60:
        raise EmailConfigurationError(
            "SMTP_PORT or SMTP_TIMEOUT_SECONDS is outside its valid range"
        )

    username = os.getenv("SMTP_USERNAME", "").strip() or None
    password = os.getenv("SMTP_PASSWORD", "") or None
    if bool(username) != bool(password):
        raise EmailConfigurationError(
            "SMTP_USERNAME and SMTP_PASSWORD must be configured together"
        )

    use_tls = _read_boolean_setting("SMTP_USE_TLS", default=True)
    use_ssl = _read_boolean_setting("SMTP_USE_SSL", default=False)
    if use_tls == use_ssl:
        raise EmailConfigurationError(
            "Configure exactly one SMTP transport: STARTTLS or implicit SSL"
        )

    return SMTPSettings(
        host=host,
        port=port,
        from_email=from_email,
        username=username,
        password=password,
        use_tls=use_tls,
        use_ssl=use_ssl,
        timeout=timeout,
    )


def _read_boolean_setting(name: str, *, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    raise EmailConfigurationError(f"{name} must be true or false")


def send_password_recovery_notification(
    user: User,
    owners: list[User],
    settings: SMTPSettings,
) -> None:
    recipients = sorted({owner.email for owner in owners})
    if not recipients:
        raise EmailConfigurationError(
            "No active team owner is available to receive recovery requests"
        )

    message = EmailMessage()
    message["Subject"] = "Password reset requested"
    message["From"] = settings.from_email
    message["To"] = ", ".join(recipients)
    message.set_content(
        f"A password reset was requested for {user.full_name} ({user.email}).\n\n"
        "Sign in to UrbanNest Realty CRM and use the team page to generate a "
        "temporary password for this account. Share that password with the user "
        "through a separate, trusted channel.\n\n"
        "No password was changed by this request."
    )

    context = ssl.create_default_context()
    if settings.use_ssl:
        with smtplib.SMTP_SSL(
            settings.host,
            settings.port,
            timeout=settings.timeout,
            context=context,
        ) as server:
            _send_message(server, message, settings)
        return

    with smtplib.SMTP(
        settings.host,
        settings.port,
        timeout=settings.timeout,
    ) as server:
        server.ehlo()
        if settings.use_tls:
            server.starttls(context=context)
            server.ehlo()
        _send_message(server, message, settings)


def _send_message(
    server: smtplib.SMTP | smtplib.SMTP_SSL,
    message: EmailMessage,
    settings: SMTPSettings,
) -> None:
    if settings.username is not None and settings.password is not None:
        server.login(settings.username, settings.password)
    refused = server.send_message(message)
    if refused:
        raise smtplib.SMTPRecipientsRefused(refused)
