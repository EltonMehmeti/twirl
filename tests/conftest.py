import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from twirl.app import create_app
from twirl.config import Settings
from twirl.db import get_db

ROOT = Path(__file__).resolve().parents[1]
TEST_DB_URL = os.environ.get(
    "TWIRL_TEST_DATABASE_URL", "postgresql+psycopg://twirl:twirl@localhost:5433/twirl_test"
)


def _alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL, pool_size=10, max_overflow=60)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(TEST_DB_URL), "head")
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=TEST_DB_URL,
        media_root=tmp_path / "media",
        secret_key="test-secret",
        run_scheduler=False,
    )


@pytest.fixture
def app(settings, db):
    application = create_app(settings)

    def _db_override():
        # Release the test's savepoint first, so a route's rollback only undoes the route's own work.
        db.commit()
        yield db

    application.dependency_overrides[get_db] = _db_override
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


from twirl.models import Base  # noqa: E402


@pytest.fixture
def committed(engine):
    """For tests that need real commits across connections. Truncates everything afterwards."""
    yield engine
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
