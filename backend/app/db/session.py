from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from collections.abc import Generator

from app.db.config import get_database_url, get_pool_options


engine = create_engine(
    get_database_url(),
    pool_pre_ping=True,
    **get_pool_options(),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
