import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url


BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env", override=False)


def get_database_url() -> URL:
    raw_url = os.getenv("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("DATABASE_URL must be set in the environment or backend/.env")

    url = make_url(raw_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise RuntimeError("DATABASE_URL must use PostgreSQL with the psycopg driver")
    return url


def get_pool_options() -> dict[str, int]:
    try:
        options = {
            "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "0")),
            "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        }
    except ValueError as exc:
        raise RuntimeError("Database pool settings must be integers") from exc

    if options["pool_size"] < 1:
        raise RuntimeError("DB_POOL_SIZE must be at least 1")
    if options["max_overflow"] < 0:
        raise RuntimeError("DB_MAX_OVERFLOW cannot be negative")
    if options["pool_timeout"] < 1 or options["pool_recycle"] < 1:
        raise RuntimeError("Database pool timeout and recycle values must be positive")
    return options
