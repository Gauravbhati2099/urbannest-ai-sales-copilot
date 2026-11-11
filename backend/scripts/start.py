from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.rate_limit import rate_limit_setting
from app.core.security import get_auth_settings
from app.db.config import get_database_url, get_pool_options


logger = logging.getLogger("urbannest.startup")
RATE_LIMIT_SETTINGS = (
    ("LOGIN_RATE_LIMIT_PER_IP", 30),
    ("LOGIN_RATE_LIMIT_PER_EMAIL", 10),
    ("LOGIN_RATE_WINDOW_SECONDS", 900),
    ("PUBLIC_LEAD_RATE_LIMIT", 10),
    ("PUBLIC_LEAD_RATE_WINDOW_SECONDS", 600),
    ("AUDIT_STREAMS_GLOBAL_LIMIT", 10),
    ("AUDIT_STREAMS_PER_USER_LIMIT", 2),
)


def _validate_configuration() -> int:
    get_database_url()
    get_pool_options()
    get_auth_settings()
    for name, default in RATE_LIMIT_SETTINGS:
        rate_limit_setting(name, default)

    api_prefix = os.getenv("API_V1_PREFIX", "/api/v1").rstrip("/")
    if not api_prefix.startswith("/"):
        raise RuntimeError("API_V1_PREFIX must start with '/'")

    try:
        ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata"))
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError("APP_TIMEZONE must be a valid IANA timezone") from exc

    origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if not origins:
        raise RuntimeError("CORS_ORIGINS must contain at least one frontend origin")
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            valid_port = parsed.port is None or 1 <= parsed.port <= 65535
            valid_host = bool(parsed.hostname)
        except ValueError as exc:
            raise RuntimeError(
                "CORS_ORIGINS must contain valid http(s) origins without paths"
            ) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not valid_host
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or not valid_port
        ):
            raise RuntimeError(
                "CORS_ORIGINS must contain exact http(s) origins without paths"
            )

    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError as exc:
        raise RuntimeError("PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("PORT must be between 1 and 65535")
    return port


def _check_database_connection() -> None:
    engine = create_engine(
        get_database_url(),
        pool_pre_ping=True,
        **get_pool_options(),
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def _upgrade_and_verify_schema() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "head")

    script = ScriptDirectory.from_config(config)
    engine = create_engine(get_database_url(), pool_pre_ping=True, **get_pool_options())
    try:
        with engine.connect() as connection:
            current_heads = set(
                MigrationContext.configure(connection).get_current_heads()
            )
    finally:
        engine.dispose()

    expected_heads = set(script.get_heads())
    if current_heads != expected_heads:
        raise RuntimeError(
            "Database migrations did not reach the application head; refusing to start"
        )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    port = _validate_configuration()
    logger.info("Startup configuration checks passed")
    _check_database_connection()
    logger.info("Database connection check passed")
    _upgrade_and_verify_schema()
    logger.info("Database migrations are up to date")

    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
