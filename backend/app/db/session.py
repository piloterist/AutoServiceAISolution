"""SQLAlchemy engine/session wiring.

The engine is built once from `DATABASE_URL` (env var driven, see app.core.config).
Routes use `get_db` as a FastAPI dependency; synchronous DB calls inside async
route handlers are safe because FastAPI runs `def` endpoints in a threadpool.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
