import base64

import pytest
from fastapi.testclient import TestClient

from twirl.app import create_app
from twirl.config import normalize_database_url
from twirl.db import get_db
from twirl.storage import MemoryStorage


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("postgres://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ],
)
def test_database_url_is_normalised(raw, expected):
    assert normalize_database_url(raw) == expected


def _client(settings, db, **overrides):
    app = create_app(settings.model_copy(update=overrides))

    def _db():
        db.commit()
        yield db

    app.dependency_overrides[get_db] = _db
    return app, TestClient(app)


def test_jobs_endpoint_requires_the_secret(settings, db):
    _, c = _client(settings, db, cron_secret="s3cret")
    assert c.post("/internal/jobs").status_code == 401
    assert c.post("/internal/jobs", headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = c.post("/internal/jobs", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    assert set(ok.json()) == {"deliver", "expire_requests", "no_shows", "not_returned"}


def test_jobs_endpoint_is_off_without_a_secret(settings, db):
    _, c = _client(settings, db, cron_secret="")
    assert c.post("/internal/jobs", headers={"Authorization": "Bearer "}).status_code == 404


def test_basic_auth_gate(settings, db):
    _, c = _client(settings, db, basic_auth="team:pass123")
    assert c.get("/").status_code == 401
    token = base64.b64encode(b"team:pass123").decode()
    assert c.get("/", headers={"Authorization": f"Basic {token}"}).status_code == 200
    assert c.get("/healthz").status_code == 200  # uptime checks stay open


def test_media_is_served_from_object_storage(settings, db):
    app, c = _client(settings, db, storage_backend="memory")
    assert isinstance(app.state.storage, MemoryStorage)
    app.state.storage.put("styles/1/x-thumb.webp", b"RIFFxxxxWEBP", "image/webp")
    r = c.get("/media/styles/1/x-thumb.webp")
    assert (r.status_code, r.headers["content-type"], r.content) == (
        200,
        "image/webp",
        b"RIFFxxxxWEBP",
    )
    assert "max-age" in r.headers["cache-control"]
    assert c.get("/media/nope.webp").status_code == 404
