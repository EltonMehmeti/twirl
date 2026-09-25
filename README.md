# Twirl

Dress rental booking for Kosovo shops. Spec: `docs/twirl-requirements-spec.md`.

## Develop

```bash
docker compose up -d db
uv sync
uv run alembic upgrade head
uv run pytest
uv run uvicorn twirl.app:create_app --factory --reload
```

Tests use the `twirl_test` database on port 5433 and rebuild its schema on every run.
