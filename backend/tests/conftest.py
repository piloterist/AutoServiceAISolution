"""Shared pytest fixtures.

Tests run against a real PostgreSQL database (a dedicated `<db>_test`
database, see app.core.config.Settings.test_database_url) rather than
SQLite, because the schema relies on Postgres-only features (JSONB,
`ON CONFLICT` upsert) that a lighter substitute cannot faithfully emulate.
"""

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 - ensure models are registered on Base.metadata
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app as fastapi_app


def _test_database_url() -> str:
    settings = get_settings()
    if settings.test_database_url:
        return settings.test_database_url
    url = make_url(settings.database_url)
    return str(url.set(database=f"{url.database}_test"))


engine = create_engine(_test_database_url(), future=True)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Generator[None, None, None]:
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables() -> Generator[None, None, None]:
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def api_token() -> str:
    return get_settings().api_token


@pytest.fixture()
def auth_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}"}


@pytest.fixture()
def sample_import_payload() -> dict:
    return {
        "source": "alpha-auto",
        "branch": "kahovka",
        "entity": "work_orders",
        "exported_at": "2026-09-13T10:00:00",
        "batch_id": f"test-{uuid.uuid4()}",
        "records": [
            {
                "number": "PS00010196",
                "date": "2026-09-12T18:38:09",
                "customer": "Example Customer",
                "car": "VW TIGUAN VIN XXXXXXXXX",
                "amount": 18500,
            }
        ],
    }
