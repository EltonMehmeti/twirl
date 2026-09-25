# Twirl Shop Calendar Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working slice of Twirl: shops manage dresses, a per-dress calendar, walk-ins and blocks, and receive request-to-book requests from a public storefront, with a database-level guarantee that no physical dress is ever double-booked.

**Architecture:** One FastAPI process renders HTML on the server with Jinja2 and HTMX. PostgreSQL 16 holds everything; a GiST exclusion constraint on (item, blocked date range) is the double-booking guarantee. Domain logic lives in plain functions under `twirl/booking/` that take a SQLAlchemy `Session` and never commit; web routes own the transaction. Background jobs run in-process with APScheduler; notifications go through an outbox table.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (sync) + psycopg 3, Alembic, PostgreSQL 16 (+ `btree_gist`), Jinja2 + HTMX, Babel, argon2-cffi, Pillow, APScheduler 3, sqladmin, phonenumbers, segno, pytest, uv, Docker Compose.

**Spec:** `docs/twirl-requirements-spec.md` (sections 5, 9, 4.2, 8 are the ones this plan implements).

## Global Constraints

- Python `>=3.12`; PostgreSQL `16`; server-rendered HTML only, no SPA, no client framework on public pages.
- Money is stored as integer cents, currency EUR only.
- Rental dates are calendar `date`s, never timestamps. Business time zone is `Europe/Belgrade`.
- The exclusion constraint `ex_bookings_item_overlap` is the double-booking guarantee. Never disable it, never bypass it for imports.
- Active (item-occupying) statuses are exactly `hold`, `pending_shop`, `confirmed`, `picked_up`.
- Domain functions flush but never commit. Web routes call `db.commit()` once on success and `db.rollback()` on handled errors.
- Every POST handler depends on `verify_csrf`.
- Every shop-side query filters by the logged-in shop (`ctx.shop.id`). Another shop's row is a 404, never a 403.
- UI default language is Albanian (`sq`), English (`en`) secondary. Source strings in code and templates are English msgids.
- No payments, no holds, no renter accounts, no SMS in this plan.

## Deviations from the spec (decided in this plan)

1. **`at_risk` does not occupy the item.** Spec §5.3 lists `at_risk` in the exclusion constraint's `WHERE`. That makes the §5.6 walk-in override impossible: the walk-in insert would violate the constraint against the booking it just flagged. Here `at_risk` means "displaced, needs a new dress"; it re-enters the constraint when swapped back to `confirmed`.
2. **Auth is Starlette signed-cookie sessions + argon2**, not fastapi-users (which requires async SQLAlchemy).
3. **Renters are `users` rows of kind `renter`** created from name + phone with no verification (no SMS provider yet). Spam is limited by a honeypot and a per-IP rate limit.
4. **No per-item cleaning override** in this slice. Buffers come from the shop.
5. **Style availability is an HTMX HTML fragment**, not a JSON endpoint.
6. **Blocks are removed by cancelling** (`cancelled_by_shop`), never deleted, so history survives.
7. **Automatic no-show** fires one full day after the pickup date, not on it. The Today list shows overdue pickups before that.
8. **Walk-ins have a "picked up now" checkbox** so a dress handed over on the spot is `picked_up` immediately and never auto-released.

## Out of scope (later plans)

Visual design and Tailwind build; holds, card payments and refunds; phone OTP and SMS; renter accounts, marketplace search, occasion pages, reviews; statements and analytics; CSV catalog and agenda import; `audit_log`; shop agreement acceptance; SLA nudges counted in opening hours; instant-mode unlock rules and auto-revert; deployment, backups, monitoring, PWA manifest.

## File Structure

```
pyproject.toml, alembic.ini, babel.cfg, docker-compose.yml, docker/initdb.sql, .env.example, README.md
migrations/env.py, migrations/versions/0001..0004_*.py
src/twirl/
  config.py            Settings (env prefix TWIRL_)
  db.py                Database (engine + sessionmaker), get_db dependency
  clock.py             now() / today() in Europe/Belgrade
  app.py               create_app(): middleware, routers, admin, scheduler lifespan
  models/              base.py, users.py, shops.py, catalog.py, bookings.py, notifications.py
  slugs.py             shop slug validation + reserved words
  codes.py             4-char item codes, 6-char booking refs
  phones.py            E.164 normalisation (default region XK)
  catalog.py           styles, items, sizes, style images
  customers.py         get-or-create renter by phone, link to shop
  booking/
    errors.py          BookingError hierarchy, is_exclusion_violation
    dates.py           ShopRules, RentalDates, derive/validate/blocked_range (pure)
    rules.py           rules_for_shop(shop)
    actor.py           Actor, SYSTEM
    states.py          allowed transitions
    timeline.py        transition(), record_created()
    availability.py    overlap queries, free items, style availability
    requests.py        create_request() for storefront requests
    staff.py           walk-ins with override, blocks, swaps, lifecycle actions
    board.py           Today board, week calendar
  notify/              templates.py, outbox.py, payloads.py, senders.py
  jobs.py              expire requests, no-shows, not-returned, deliver notifications
  scheduler.py         APScheduler wiring
  auth/                passwords.py, csrf.py, deps.py
  ratelimit.py         in-memory sliding window limiter, client_ip()
  i18n.py              locales, translations, N_()
  images.py            upload pipeline (Pillow)
  storage.py           LocalStorage, get_storage
  cli.py               create-admin, create-shop, publish-shop
  web/                 templating.py, forms.py, messages.py, health.py, pages.py, auth.py,
                       shop_settings.py, shop_catalog.py, shop_bookings.py, storefront.py, admin.py
  templates/           base.html, home.html, auth/, shop/, storefront/
  static/              app.css, htmx.min.js
  locale/sq/LC_MESSAGES/messages.po (+ .mo)
tests/                 conftest.py, factories.py, helpers.py, test_*.py
```

---

### Task 1: Project scaffold, database harness, health check

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `docker-compose.yml`, `docker/initdb.sql`, `README.md`
- Create: `alembic.ini` (generated), `migrations/env.py` (replace generated)
- Create: `src/twirl/__init__.py`, `src/twirl/config.py`, `src/twirl/db.py`, `src/twirl/app.py`
- Create: `src/twirl/models/__init__.py`, `src/twirl/models/base.py`
- Create: `src/twirl/web/__init__.py`, `src/twirl/web/health.py`
- Test: `tests/__init__.py`, `tests/conftest.py`, `tests/test_health.py`

**Interfaces:**
- Produces: `Settings`, `get_settings()`; `Database(url)` with `.engine`, `.sessionmaker`; `get_db(request) -> Iterator[Session]`; `create_app(settings) -> FastAPI`; `Base`, `Timestamps`, `check_in(column, enum_cls, name=None)`; pytest fixtures `engine`, `db`, `settings`, `app`, `client`.

- [ ] **Step 1: Initialise the repo and write project files**

```bash
cd /home/elton/PycharmProjects/twirl && git init -b main
mkdir -p src/twirl/models src/twirl/web tests docker
```

`pyproject.toml`:

```toml
[project]
name = "twirl"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy>=2.0.30",
  "psycopg[binary]>=3.2",
  "alembic>=1.13",
  "pydantic-settings>=2.4",
  "jinja2>=3.1",
  "python-multipart>=0.0.9",
  "itsdangerous>=2.2",
  "argon2-cffi>=23.1",
  "pillow>=10.4",
  "babel>=2.16",
  "apscheduler>=3.10,<4",
  "httpx>=0.27",
  "sqladmin>=0.19",
  "phonenumbers>=8.13",
  "segno>=1.6",
  "tzdata>=2024.1",
]

[project.scripts]
twirl = "twirl.cli:main"

[dependency-groups]
dev = ["pytest>=8.3", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/twirl"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.env
var/
```

`.env.example`:

```
TWIRL_DATABASE_URL=postgresql+psycopg://twirl:twirl@localhost:5433/twirl
TWIRL_SECRET_KEY=change-me-to-a-long-random-string
TWIRL_BASE_URL=http://localhost:8000
TWIRL_RUN_SCHEDULER=false
TWIRL_SMTP_HOST=
TWIRL_TELEGRAM_BOT_TOKEN=
TWIRL_TELEGRAM_ADMIN_CHAT_ID=
```

`docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: twirl
      POSTGRES_PASSWORD: twirl
      POSTGRES_DB: twirl
    ports:
      - "5433:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/initdb.sql:/docker-entrypoint-initdb.d/initdb.sql:ro
volumes:
  pgdata:
```

`docker/initdb.sql`:

```sql
CREATE DATABASE twirl_test OWNER twirl;
```

`README.md`:

````markdown
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
````

- [ ] **Step 2: Write config, database and base model modules**

`src/twirl/__init__.py`: empty file. `src/twirl/web/__init__.py`: empty file. `tests/__init__.py`: empty file.

`src/twirl/config.py`:

```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TWIRL_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://twirl:twirl@localhost:5433/twirl"
    secret_key: str = "dev-insecure-change-me"
    https_only: bool = False
    base_url: str = "http://localhost:8000"
    media_root: Path = Path("var/media")
    run_scheduler: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "Twirl <no-reply@twirl.local>"
    telegram_bot_token: str = ""
    telegram_admin_chat_id: str = ""
    trust_cf_connecting_ip: bool = False
    request_rate_limit_per_hour: int = 5
    request_sla_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`src/twirl/db.py`:

```python
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request


class Database:
    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)
        self.sessionmaker = sessionmaker(self.engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.db.sessionmaker() as session:
        yield session
```

`src/twirl/models/base.py`:

```python
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {int: BigInteger}


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def check_in(column: str, enum_cls: type[StrEnum], name: str | None = None) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name or column)
```

`src/twirl/models/__init__.py`:

```python
from twirl.models.base import Base

__all__ = ["Base"]
```

- [ ] **Step 3: Write the failing health test and the test harness**

`tests/conftest.py`:

```python
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
```

`tests/test_health.py`:

```python
def test_healthz_reports_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 4: Start Postgres, install, generate Alembic, run test to verify it fails**

```bash
docker compose up -d db
uv sync
uv run alembic init migrations
sed -i 's|^sqlalchemy.url = .*|sqlalchemy.url =|' alembic.ini
```

Replace `migrations/env.py` entirely with:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from twirl.config import get_settings
from twirl.models import Base

config = context.config
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": url}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.app'`.

- [ ] **Step 5: Implement the app factory and health route**

`src/twirl/web/health.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from twirl.db import get_db

router = APIRouter()


@router.get("/healthz")
def healthz(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
```

`src/twirl/app.py`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from twirl.config import Settings, get_settings
from twirl.db import Database
from twirl.web import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    app.state.db.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Twirl", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.include_router(health.router)
    return app
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: scaffold FastAPI app, Postgres harness and health check"
```

---

### Task 2: Users and shops

**Files:**
- Create: `src/twirl/models/users.py`, `src/twirl/models/shops.py`, `src/twirl/slugs.py`
- Modify: `src/twirl/models/__init__.py`
- Create: `migrations/versions/0001_users_and_shops.py` (autogenerated)
- Test: `tests/factories.py`, `tests/test_shops.py`

**Interfaces:**
- Consumes: `Base`, `Timestamps`, `check_in` from Task 1.
- Produces: `User`, `UserKind`; `Shop`, `ShopHours`, `ShopClosure`, `ShopUser`, `ShopCustomer`, `ShopStatus`, `BookingMode`, `ShopRole`; `RESERVED_SLUGS`, `is_valid_slug(slug) -> bool`; factories `make_user`, `make_shop`, `make_shop_user`.

- [ ] **Step 1: Write the failing tests**

`tests/factories.py`:

```python
import itertools

from twirl.models import Shop, ShopUser, User

_seq = itertools.count(1)


def make_user(db, *, kind="shop", name="Test User", email=None, phone=None, password_hash=None):
    n = next(_seq)
    user = User(
        kind=kind,
        name=name,
        email=email if email is not None else f"user{n}@example.com",
        phone=phone,
        password_hash=password_hash,
    )
    db.add(user)
    db.flush()
    return user


def make_shop(db, *, slug=None, status="published", booking_mode="request", **fields):
    n = next(_seq)
    shop = Shop(
        slug=slug or f"shop-{n}",
        name=fields.pop("name", f"Shop {n}"),
        city=fields.pop("city", "Ferizaj"),
        status=status,
        booking_mode=booking_mode,
        **fields,
    )
    db.add(shop)
    db.flush()
    return shop


def make_shop_user(db, shop, *, role="owner", email=None, password_hash=None):
    user = make_user(db, kind="shop", email=email, password_hash=password_hash)
    db.add(ShopUser(shop_id=shop.id, user_id=user.id, role=role))
    db.flush()
    return user
```

`tests/test_shops.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from tests.factories import make_shop, make_shop_user
from twirl.models import ShopUser
from twirl.slugs import is_valid_slug


def test_shop_has_spec_default_rules(db):
    shop = make_shop(db)
    db.refresh(shop)
    assert (
        shop.pickup_lead_days,
        shop.return_after_days,
        shop.prep_days,
        shop.cleaning_days,
        shop.max_rental_days,
    ) == (2, 1, 0, 1, 7)
    assert shop.booking_mode == "request"


def test_slug_is_unique(db):
    make_shop(db, slug="bella")
    with pytest.raises(IntegrityError), db.begin_nested():
        make_shop(db, slug="bella")


def test_cleaning_days_range_is_enforced(db):
    with pytest.raises(IntegrityError), db.begin_nested():
        make_shop(db, cleaning_days=9)


def test_user_belongs_to_at_most_one_shop(db):
    shop_a = make_shop(db)
    shop_b = make_shop(db)
    user = make_shop_user(db, shop_a)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(ShopUser(shop_id=shop_b.id, user_id=user.id, role="staff"))
        db.flush()


@pytest.mark.parametrize(
    "slug, valid",
    [("bella-dresses", True), ("b1", True), ("Bella", False), ("-bella", False),
     ("admin", False), ("shop", False), ("a", False)],
)
def test_slug_validation(slug, valid):
    assert is_valid_slug(slug) is valid
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_shops.py -v`
Expected: FAIL with `ImportError: cannot import name 'Shop' from 'twirl.models'`.

- [ ] **Step 3: Implement models and slug validation**

`src/twirl/models/users.py`:

```python
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from twirl.models.base import Base, Timestamps, check_in


class UserKind(StrEnum):
    RENTER = "renter"
    SHOP = "shop"
    ADMIN = "admin"


class User(Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (check_in("kind", UserKind),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(5), default="sq", server_default=text("'sq'"))
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

`src/twirl/models/shops.py`:

```python
from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, SmallInteger, String, Text, Time, func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twirl.models.base import Base, Timestamps, check_in
from twirl.models.users import User


class ShopStatus(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    PUBLISHED = "published"
    SUSPENDED = "suspended"


class BookingMode(StrEnum):
    REQUEST = "request"
    INSTANT = "instant"


class ShopRole(StrEnum):
    OWNER = "owner"
    STAFF = "staff"


def _small(default: int):
    return mapped_column(SmallInteger, default=default, server_default=text(str(default)))


class Shop(Timestamps, Base):
    __tablename__ = "shops"
    __table_args__ = (
        check_in("status", ShopStatus),
        check_in("booking_mode", BookingMode),
        CheckConstraint("pickup_lead_days BETWEEN 0 AND 5", name="pickup_lead_days"),
        CheckConstraint("return_after_days BETWEEN 0 AND 3", name="return_after_days"),
        CheckConstraint("prep_days BETWEEN 0 AND 2", name="prep_days"),
        CheckConstraint("cleaning_days BETWEEN 0 AND 5", name="cleaning_days"),
        CheckConstraint("max_rental_days BETWEEN 1 AND 14", name="max_rental_days"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(60))
    address: Mapped[str] = mapped_column(String(255), default="", server_default=text("''"))
    phone: Mapped[str | None] = mapped_column(String(20))
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    viber: Mapped[str | None] = mapped_column(String(20))
    instagram: Mapped[str | None] = mapped_column(String(60))
    terms_text: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    pickup_lead_days: Mapped[int] = _small(2)
    return_after_days: Mapped[int] = _small(1)
    prep_days: Mapped[int] = _small(0)
    cleaning_days: Mapped[int] = _small(1)
    max_rental_days: Mapped[int] = _small(7)
    booking_mode: Mapped[str] = mapped_column(
        String(16), default=BookingMode.REQUEST.value, server_default=text("'request'")
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ShopStatus.DRAFT.value, server_default=text("'draft'")
    )

    hours: Mapped[list["ShopHours"]] = relationship(
        back_populates="shop", order_by="ShopHours.weekday", cascade="all, delete-orphan"
    )
    closures: Mapped[list["ShopClosure"]] = relationship(
        back_populates="shop", order_by="ShopClosure.starts_on", cascade="all, delete-orphan"
    )


class ShopHours(Base):
    __tablename__ = "shop_hours"
    __table_args__ = (CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),)

    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True)
    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    opens: Mapped[time | None] = mapped_column(Time)
    closes: Mapped[time | None] = mapped_column(Time)
    closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    shop: Mapped[Shop] = relationship(back_populates="hours")


class ShopClosure(Timestamps, Base):
    __tablename__ = "shop_closures"
    __table_args__ = (CheckConstraint("ends_on >= starts_on", name="range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))

    shop: Mapped[Shop] = relationship(back_populates="closures")


class ShopUser(Timestamps, Base):
    __tablename__ = "shop_users"
    __table_args__ = (check_in("role", ShopRole),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    role: Mapped[str] = mapped_column(String(16))

    shop: Mapped[Shop] = relationship()
    user: Mapped[User] = relationship()


class ShopCustomer(Base):
    __tablename__ = "shop_customers"

    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    first_booking_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
```

`src/twirl/models/__init__.py`:

```python
from twirl.models.base import Base
from twirl.models.shops import (
    BookingMode, Shop, ShopClosure, ShopCustomer, ShopHours, ShopRole, ShopStatus, ShopUser,
)
from twirl.models.users import User, UserKind

__all__ = [
    "Base", "BookingMode", "Shop", "ShopClosure", "ShopCustomer", "ShopHours", "ShopRole",
    "ShopStatus", "ShopUser", "User", "UserKind",
]
```

`src/twirl/slugs.py`:

```python
import re

RESERVED_SLUGS = frozenset(
    {"admin", "api", "healthz", "lang", "login", "logout", "media", "r", "shop", "static"}
)
_SLUG_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.fullmatch(slug)) and slug not in RESERVED_SLUGS
```

- [ ] **Step 4: Generate and apply the migration**

```bash
uv run alembic revision --autogenerate --rev-id 0001 -m "users and shops"
uv run alembic upgrade head
```

Open `migrations/versions/0001_users_and_shops.py` and confirm it creates `users`, `shops`, `shop_hours`, `shop_closures`, `shop_users`, `shop_customers` with the `ck_shops_cleaning_days` check constraint.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_shops.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: users and shops schema with rule defaults and slug validation"
```

---

### Task 3: Catalog — styles, items, codes

**Files:**
- Create: `src/twirl/models/catalog.py`, `src/twirl/codes.py`, `src/twirl/catalog.py`
- Modify: `src/twirl/models/__init__.py`, `tests/factories.py`
- Create: `migrations/versions/0002_catalog.py` (autogenerated)
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `Shop`, `Base`, `Timestamps`, `check_in`.
- Produces: `Style`, `StyleImage`, `Item`, `Occasion`, `ColourFamily`, `DressLength`, `ItemStatus`; `CODE_ALPHABET`, `random_code(length) -> str`, `new_item_code(session, shop_id) -> str`; `normalize_size(raw) -> str`, `size_sort_key(size) -> tuple`, `next_style_code(session, shop_id) -> str`, `create_style(session, shop, *, name, price_cents, description="", occasion_tags=(), colour_family=None, length=None, stretch=False, adjustable_back=False, published=False) -> Style`, `add_items(session, style, *, size, quantity) -> list[Item]`; factories `make_style`, `make_item`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/factories.py`:

```python
from twirl.codes import new_item_code  # noqa: E402
from twirl.models import Item, Style  # noqa: E402


def make_style(db, shop, *, name="Silk gown", price_cents=5000, published=True, code=None):
    n = next(_seq)
    style = Style(
        shop_id=shop.id, code=code or f"S{n:04d}", name=name, price_cents=price_cents,
        published=published,
    )
    db.add(style)
    db.flush()
    return style


def make_item(db, style, *, size="38", status="active", code=None):
    item = Item(
        shop_id=style.shop_id, style_id=style.id, size=size, status=status,
        code=code or new_item_code(db, style.shop_id),
    )
    db.add(item)
    db.flush()
    return item
```

`tests/test_catalog.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from tests.factories import make_item, make_shop, make_style
from twirl.catalog import add_items, create_style, normalize_size, size_sort_key
from twirl.codes import CODE_ALPHABET, random_code


def test_random_code_uses_unambiguous_alphabet():
    for _ in range(200):
        code = random_code(4)
        assert len(code) == 4
        assert set(code) <= set(CODE_ALPHABET)


def test_style_codes_are_sequential_per_shop(db):
    shop = make_shop(db)
    first = create_style(db, shop, name="Red gown", price_cents=4500)
    second = create_style(db, shop, name="Blue gown", price_cents=6000)
    other = create_style(db, make_shop(db), name="Other", price_cents=100)
    assert (first.code, second.code, other.code) == ("001", "002", "001")


def test_create_style_rejects_unknown_occasion(db):
    with pytest.raises(ValueError):
        create_style(db, make_shop(db), name="X", price_cents=100, occasion_tags=["party"])


def test_add_items_creates_one_item_per_physical_dress(db):
    style = create_style(db, make_shop(db), name="Gold", price_cents=7000)
    items = add_items(db, style, size=" m ", quantity=3)
    assert len(items) == 3
    assert {i.size for i in items} == {"M"}
    assert len({i.code for i in items}) == 3


@pytest.mark.parametrize("quantity", [0, 21])
def test_add_items_rejects_bad_quantity(db, quantity):
    style = create_style(db, make_shop(db), name="Gold", price_cents=7000)
    with pytest.raises(ValueError):
        add_items(db, style, size="38", quantity=quantity)


def test_item_code_unique_per_shop(db):
    style = make_style(db, make_shop(db))
    make_item(db, style, code="ACDE")
    with pytest.raises(IntegrityError), db.begin_nested():
        make_item(db, style, code="ACDE")


def test_normalize_size_rejects_blank():
    with pytest.raises(ValueError):
        normalize_size("   ")


def test_sizes_sort_numbers_then_letters():
    assert sorted(["M", "40", "XS", "38", "L"], key=size_sort_key) == ["38", "40", "XS", "M", "L"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.codes'`.

- [ ] **Step 3: Implement catalog models, codes and service**

`src/twirl/models/catalog.py`:

```python
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twirl.models.base import Base, Timestamps, check_in
from twirl.models.shops import Shop


class Occasion(StrEnum):
    WEDDING = "wedding"
    ENGAGEMENT = "engagement"
    MATURA = "matura"
    HENNA_NIGHT = "henna_night"
    EVENING = "evening"


class ColourFamily(StrEnum):
    BLACK = "black"
    WHITE = "white"
    RED = "red"
    PINK = "pink"
    BLUE = "blue"
    GREEN = "green"
    GOLD = "gold"
    SILVER = "silver"
    BEIGE = "beige"
    PURPLE = "purple"
    MULTI = "multi"


class DressLength(StrEnum):
    MINI = "mini"
    MIDI = "midi"
    MAXI = "maxi"


class ItemStatus(StrEnum):
    ACTIVE = "active"
    CLEANING = "cleaning"
    REPAIR = "repair"
    RETIRED = "retired"
    LOST = "lost"


class Style(Timestamps, Base):
    __tablename__ = "styles"
    __table_args__ = (
        UniqueConstraint("shop_id", "code"),
        CheckConstraint("price_cents >= 0", name="price"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    price_cents: Mapped[int] = mapped_column(Integer)
    occasion_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default=text("'{}'")
    )
    colour_family: Mapped[str | None] = mapped_column(String(16))
    length: Mapped[str | None] = mapped_column(String(8))
    stretch: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    adjustable_back: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    shop: Mapped[Shop] = relationship()
    images: Mapped[list["StyleImage"]] = relationship(
        back_populates="style", order_by="StyleImage.position", cascade="all, delete-orphan"
    )
    items: Mapped[list["Item"]] = relationship(back_populates="style", order_by="Item.id")


class StyleImage(Timestamps, Base):
    __tablename__ = "style_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    style_id: Mapped[int] = mapped_column(ForeignKey("styles.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    storage_key: Mapped[str] = mapped_column(String(200))
    width: Mapped[int] = mapped_column(SmallInteger)
    height: Mapped[int] = mapped_column(SmallInteger)

    style: Mapped[Style] = relationship(back_populates="images")


class Item(Timestamps, Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("shop_id", "code"),
        UniqueConstraint("id", "style_id", "shop_id", name="uq_items_id_style_shop"),
        check_in("status", ItemStatus),
        Index("ix_items_style_size", "style_id", "size"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    style_id: Mapped[int] = mapped_column(ForeignKey("styles.id"))
    code: Mapped[str] = mapped_column(String(4))
    size: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(
        String(16), default=ItemStatus.ACTIVE.value, server_default=text("'active'")
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))

    style: Mapped[Style] = relationship(back_populates="items")
```

`src/twirl/models/__init__.py`:

```python
from twirl.models.base import Base
from twirl.models.catalog import ColourFamily, DressLength, Item, ItemStatus, Occasion, Style, StyleImage
from twirl.models.shops import (
    BookingMode, Shop, ShopClosure, ShopCustomer, ShopHours, ShopRole, ShopStatus, ShopUser,
)
from twirl.models.users import User, UserKind

__all__ = [
    "Base", "BookingMode", "ColourFamily", "DressLength", "Item", "ItemStatus", "Occasion",
    "Shop", "ShopClosure", "ShopCustomer", "ShopHours", "ShopRole", "ShopStatus", "ShopUser",
    "Style", "StyleImage", "User", "UserKind",
]
```

`src/twirl/codes.py`:

```python
import secrets

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from twirl.models import Item

CODE_ALPHABET = "ACDEFHJKLMNPRTUVWXY3479"


def random_code(length: int) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def new_item_code(session: Session, shop_id: int) -> str:
    for _ in range(20):
        code = random_code(4)
        taken = session.scalar(select(exists().where(Item.shop_id == shop_id, Item.code == code)))
        if not taken:
            return code
    raise RuntimeError("could not allocate a free item code")
```

`src/twirl/catalog.py`:

```python
from collections.abc import Iterable

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from twirl.codes import new_item_code
from twirl.models import ColourFamily, DressLength, Item, Occasion, Shop, Style

LETTER_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]
MAX_ITEMS_PER_ADD = 20


def normalize_size(raw: str) -> str:
    size = raw.strip().upper()
    if not size or len(size) > 8:
        raise ValueError("invalid size")
    return size


def size_sort_key(size: str) -> tuple[int, float, str]:
    if size.replace(".", "", 1).isdigit():
        return (0, float(size), size)
    if size in LETTER_SIZES:
        return (1, float(LETTER_SIZES.index(size)), size)
    return (2, 0.0, size)


def next_style_code(session: Session, shop_id: int) -> str:
    n = session.scalar(select(func.count()).select_from(Style).where(Style.shop_id == shop_id)) or 0
    while True:
        n += 1
        code = f"{n:03d}"
        taken = session.scalar(select(exists().where(Style.shop_id == shop_id, Style.code == code)))
        if not taken:
            return code


def create_style(
    session: Session,
    shop: Shop,
    *,
    name: str,
    price_cents: int,
    description: str = "",
    occasion_tags: Iterable[str] = (),
    colour_family: str | None = None,
    length: str | None = None,
    stretch: bool = False,
    adjustable_back: bool = False,
    published: bool = False,
) -> Style:
    tags = [Occasion(tag).value for tag in occasion_tags]
    style = Style(
        shop_id=shop.id,
        code=next_style_code(session, shop.id),
        name=name.strip(),
        price_cents=price_cents,
        description=description.strip(),
        occasion_tags=tags,
        colour_family=ColourFamily(colour_family).value if colour_family else None,
        length=DressLength(length).value if length else None,
        stretch=stretch,
        adjustable_back=adjustable_back,
        published=published,
    )
    session.add(style)
    session.flush()
    return style


def add_items(session: Session, style: Style, *, size: str, quantity: int) -> list[Item]:
    if not 1 <= quantity <= MAX_ITEMS_PER_ADD:
        raise ValueError("quantity must be between 1 and 20")
    size = normalize_size(size)
    items = []
    for _ in range(quantity):
        item = Item(
            shop_id=style.shop_id, style_id=style.id, size=size,
            code=new_item_code(session, style.shop_id),
        )
        session.add(item)
        session.flush()
        items.append(item)
    return items
```

- [ ] **Step 4: Generate and apply the migration**

```bash
uv run alembic revision --autogenerate --rev-id 0002 -m "catalog"
uv run alembic upgrade head
```

Confirm the file creates `styles`, `style_images`, `items` and the `uq_items_id_style_shop` unique constraint.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: styles, items and item codes"
```

---

### Task 4: Bookings schema and the exclusion constraint

**Files:**
- Create: `src/twirl/models/bookings.py`
- Modify: `src/twirl/models/__init__.py`, `src/twirl/codes.py`, `tests/factories.py`
- Create: `migrations/versions/0003_bookings.py` (autogenerated, then edited)
- Test: `tests/test_booking_schema.py`

**Interfaces:**
- Consumes: `Item`, `Style`, `Shop`, `User`.
- Produces: `Booking`, `BookingEvent`, `ItemConditionEvent`, `BookingKind`, `BookingStatus`, `ActorKind`, `ConditionKind`, `ACTIVE_STATUSES: tuple[str, ...]`; `new_booking_ref(session) -> str`; factories `make_booking`, `make_renter`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/factories.py`:

```python
from twirl.models import Booking  # noqa: E402


def make_renter(db, *, name="Arta", phone=None):
    n = next(_seq)
    user = User(kind="renter", name=name, phone=phone or f"+3834400{n:04d}")
    db.add(user)
    db.flush()
    return user


def make_booking(
    db, item, *, pickup, return_, status="confirmed", kind="walk_in", prep_days=0,
    cleaning_days=1, customer=None, event_date=None, created_at=None,
):
    booking = Booking(
        ref=f"T{next(_seq):05d}",
        shop_id=item.shop_id,
        style_id=item.style_id,
        item_id=item.id,
        kind=kind,
        status=status,
        pickup_date=pickup,
        return_date=return_,
        prep_days=prep_days,
        cleaning_days=cleaning_days,
        customer_id=customer.id if customer else None,
        event_date=event_date,
    )
    if created_at is not None:
        booking.created_at = created_at
    db.add(booking)
    db.flush()
    return booking
```

`tests/test_booking_schema.py`:

```python
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from tests.factories import make_booking, make_item, make_shop, make_style

D = date(2027, 5, 10)


def _item(db):
    return make_item(db, make_style(db, make_shop(db)))


def test_blocked_range_includes_prep_and_cleaning_days(db):
    booking = make_booking(db, _item(db), pickup=D, return_=D + timedelta(2), prep_days=1, cleaning_days=1)
    db.refresh(booking)
    assert booking.blocked_range.lower == D - timedelta(1)
    assert booking.blocked_range.upper == D + timedelta(4)  # canonical form: upper bound exclusive


def test_overlapping_active_bookings_on_one_item_are_rejected(db):
    item = _item(db)
    make_booking(db, item, pickup=D, return_=D + timedelta(2))
    with pytest.raises(IntegrityError) as exc, db.begin_nested():
        make_booking(db, item, pickup=D + timedelta(1), return_=D + timedelta(3))
    assert exc.value.orig.sqlstate == "23P01"


def test_cleaning_day_blocks_the_next_pickup(db):
    item = _item(db)
    make_booking(db, item, pickup=D, return_=D + timedelta(1), cleaning_days=1)
    with pytest.raises(IntegrityError), db.begin_nested():
        make_booking(db, item, pickup=D + timedelta(2), return_=D + timedelta(3))
    make_booking(db, item, pickup=D + timedelta(3), return_=D + timedelta(4))


@pytest.mark.parametrize("status", ["cancelled_by_renter", "declined", "completed", "at_risk"])
def test_inactive_statuses_do_not_occupy_the_item(db, status):
    item = _item(db)
    make_booking(db, item, pickup=D, return_=D + timedelta(2), status=status)
    make_booking(db, item, pickup=D, return_=D + timedelta(2))


def test_same_dates_on_different_items_are_fine(db):
    style = make_style(db, make_shop(db))
    make_booking(db, make_item(db, style), pickup=D, return_=D + timedelta(2))
    make_booking(db, make_item(db, style), pickup=D, return_=D + timedelta(2))


def test_booking_style_must_match_item_style(db):
    shop = make_shop(db)
    item = make_item(db, make_style(db, shop))
    other_style = make_style(db, shop)
    booking = make_booking(db, item, pickup=D, return_=D)
    with pytest.raises(IntegrityError) as exc, db.begin_nested():
        booking.style_id = other_style.id
        db.flush()
    assert exc.value.orig.sqlstate == "23503"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_booking_schema.py -v`
Expected: FAIL with `ImportError: cannot import name 'Booking' from 'twirl.models'`.

- [ ] **Step 3: Implement booking models**

`src/twirl/models/bookings.py`:

```python
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint, Computed, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer,
    SmallInteger, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twirl.models.base import Base, Timestamps, check_in
from twirl.models.catalog import Item, Style
from twirl.models.shops import Shop
from twirl.models.users import User


class BookingKind(StrEnum):
    ONLINE = "online"
    WALK_IN = "walk_in"
    PHONE = "phone"
    BLOCK = "block"


class BookingStatus(StrEnum):
    HOLD = "hold"
    PENDING_SHOP = "pending_shop"
    CONFIRMED = "confirmed"
    AT_RISK = "at_risk"
    PICKED_UP = "picked_up"
    COMPLETED = "completed"
    CANCELLED_BY_RENTER = "cancelled_by_renter"
    CANCELLED_BY_SHOP = "cancelled_by_shop"
    EXPIRED = "expired"
    NO_SHOW = "no_show"
    NOT_RETURNED = "not_returned"
    DECLINED = "declined"


class ActorKind(StrEnum):
    RENTER = "renter"
    SHOP = "shop"
    ADMIN = "admin"
    SYSTEM = "system"


class ConditionKind(StrEnum):
    INTAKE = "intake"
    RETURNED_OK = "returned_ok"
    RETURNED_ISSUE = "returned_issue"
    STATUS_CHANGE = "status_change"


ACTIVE_STATUSES: tuple[str, ...] = ("hold", "pending_shop", "confirmed", "picked_up")
_ACTIVE_SQL = "status IN ('hold', 'pending_shop', 'confirmed', 'picked_up')"


class Booking(Timestamps, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "style_id", "shop_id"],
            ["items.id", "items.style_id", "items.shop_id"],
            name="fk_bookings_item_style_shop",
        ),
        CheckConstraint("return_date >= pickup_date", name="dates_order"),
        check_in("kind", BookingKind),
        check_in("status", BookingStatus),
        ExcludeConstraint(
            ("item_id", "="),
            ("blocked_range", "&&"),
            name="ex_bookings_item_overlap",
            using="gist",
            where=text(_ACTIVE_SQL),
        ),
        Index("ix_bookings_shop_pickup", "shop_id", "pickup_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(8), unique=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    item_id: Mapped[int] = mapped_column()
    style_id: Mapped[int] = mapped_column()
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    event_date: Mapped[date | None] = mapped_column(Date)
    pickup_date: Mapped[date] = mapped_column(Date)
    return_date: Mapped[date] = mapped_column(Date)
    prep_days: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    cleaning_days: Mapped[int] = mapped_column(SmallInteger, default=1, server_default=text("1"))
    blocked_range: Mapped[Range[date]] = mapped_column(
        DATERANGE,
        Computed(
            "daterange(pickup_date - prep_days, return_date + cleaning_days, '[]')",
            persisted=True,
        ),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_channel: Mapped[str | None] = mapped_column(String(20))
    fee_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    price_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    customer_note: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    staff_note: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    reason: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    shop: Mapped[Shop] = relationship(viewonly=True)
    item: Mapped[Item] = relationship(
        viewonly=True, primaryjoin="Booking.item_id == Item.id", foreign_keys="Booking.item_id"
    )
    style: Mapped[Style] = relationship(
        viewonly=True, primaryjoin="Booking.style_id == Style.id", foreign_keys="Booking.style_id"
    )
    customer: Mapped[User | None] = relationship(viewonly=True, foreign_keys=[customer_id])


class BookingEvent(Base):
    __tablename__ = "booking_events"
    __table_args__ = (check_in("actor_kind", ActorKind),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ItemConditionEvent(Base):
    __tablename__ = "item_condition_events"
    __table_args__ = (check_in("kind", ConditionKind),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    kind: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`src/twirl/models/__init__.py`:

```python
from twirl.models.base import Base
from twirl.models.bookings import (
    ACTIVE_STATUSES, ActorKind, Booking, BookingEvent, BookingKind, BookingStatus, ConditionKind,
    ItemConditionEvent,
)
from twirl.models.catalog import ColourFamily, DressLength, Item, ItemStatus, Occasion, Style, StyleImage
from twirl.models.shops import (
    BookingMode, Shop, ShopClosure, ShopCustomer, ShopHours, ShopRole, ShopStatus, ShopUser,
)
from twirl.models.users import User, UserKind

__all__ = [
    "ACTIVE_STATUSES", "ActorKind", "Base", "Booking", "BookingEvent", "BookingKind",
    "BookingMode", "BookingStatus", "ColourFamily", "ConditionKind", "DressLength", "Item",
    "ItemConditionEvent", "ItemStatus", "Occasion", "Shop", "ShopClosure", "ShopCustomer",
    "ShopHours", "ShopRole", "ShopStatus", "ShopUser", "Style", "StyleImage", "User", "UserKind",
]
```

Append to `src/twirl/codes.py`:

```python
from twirl.models import Booking  # noqa: E402


def new_booking_ref(session: Session) -> str:
    for _ in range(20):
        ref = random_code(6)
        if not session.scalar(select(exists().where(Booking.ref == ref))):
            return ref
    raise RuntimeError("could not allocate a free booking reference")
```

- [ ] **Step 4: Generate the migration and add the extension**

```bash
uv run alembic revision --autogenerate --rev-id 0003 -m "bookings"
```

Edit `migrations/versions/0003_bookings.py`: make the first line of `upgrade()`:

```python
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
```

Confirm the `bookings` table in the file contains both of these (fix by hand if Alembic rendered them differently):

```python
sa.Column("blocked_range", postgresql.DATERANGE(), sa.Computed("daterange(pickup_date - prep_days, return_date + cleaning_days, '[]')", persisted=True), nullable=False),
postgresql.ExcludeConstraint((sa.column("item_id"), "="), (sa.column("blocked_range"), "&&"), where=sa.text("status IN ('hold', 'pending_shop', 'confirmed', 'picked_up')"), using="gist", name="ex_bookings_item_overlap"),
```

Then: `uv run alembic upgrade head`

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_booking_schema.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: bookings table with per-item exclusion constraint"
```

---

### Task 5: Date rules (pure) and booking errors

**Files:**
- Create: `src/twirl/clock.py`, `src/twirl/booking/__init__.py`, `src/twirl/booking/errors.py`, `src/twirl/booking/dates.py`, `src/twirl/booking/rules.py`
- Test: `tests/test_dates.py`

**Interfaces:**
- Consumes: `Shop`, `ShopHours`, `ShopClosure`.
- Produces: `clock.TZ`, `clock.now() -> datetime`, `clock.today() -> date`; errors `BookingError`, `InvalidDates(code)`, `InvalidTransition(src, dst)`, `NoAvailability`, `ShopNotBookable`, `ItemConflict(conflicts, overridable)`, `is_exclusion_violation(exc) -> bool`; `ShopRules`, `RentalDates(pickup, return_)`, `derive_rental_dates(event, rules) -> RentalDates`, `validate_rental_dates(dates, rules, *, today, event=None) -> None`, `blocked_range(dates, *, prep_days, cleaning_days) -> tuple[date, date]`; `rules_for_shop(shop) -> ShopRules`.

- [ ] **Step 1: Write the failing tests**

`tests/test_dates.py`:

```python
from datetime import date

import pytest

from tests.factories import make_shop
from twirl.booking.dates import (
    RentalDates, ShopRules, blocked_range, derive_rental_dates, validate_rental_dates,
)
from twirl.booking.errors import InvalidDates
from twirl.booking.rules import rules_for_shop
from twirl.models import ShopClosure, ShopHours

SAT = date(2027, 5, 15)
TODAY = date(2027, 5, 1)


def test_fixture_date_is_a_saturday():
    assert SAT.weekday() == 5


def test_default_rules_pickup_two_days_before_return_one_day_after():
    assert derive_rental_dates(SAT, ShopRules()) == RentalDates(date(2027, 5, 13), date(2027, 5, 16))


def test_return_rolls_forward_past_closed_sunday():
    rules = ShopRules(closed_weekdays=frozenset({6}))
    assert derive_rental_dates(SAT, rules).return_ == date(2027, 5, 17)


def test_pickup_rolls_back_past_a_closure():
    rules = ShopRules(closures=((date(2027, 5, 12), date(2027, 5, 13)),))
    assert derive_rental_dates(SAT, rules).pickup == date(2027, 5, 11)


def test_always_closed_shop_has_no_open_day():
    with pytest.raises(InvalidDates) as exc:
        derive_rental_dates(SAT, ShopRules(closed_weekdays=frozenset(range(7))))
    assert exc.value.code == "no_open_day"


def test_zero_lead_days_means_same_day_pickup_and_return():
    dates = derive_rental_dates(SAT, ShopRules(pickup_lead_days=0, return_after_days=0))
    assert dates == RentalDates(SAT, SAT)


@pytest.mark.parametrize(
    "pickup, return_, today, code",
    [
        (date(2027, 5, 13), date(2027, 5, 16), date(2027, 5, 14), "pickup_in_past"),
        (date(2027, 5, 16), date(2027, 5, 13), TODAY, "return_before_pickup"),
        (date(2027, 5, 1), date(2027, 5, 16), TODAY, "too_long"),
        (date(2027, 5, 16), date(2027, 5, 17), TODAY, "event_outside_rental"),
    ],
)
def test_validate_rejects_bad_dates(pickup, return_, today, code):
    with pytest.raises(InvalidDates) as exc:
        validate_rental_dates(RentalDates(pickup, return_), ShopRules(), today=today, event=SAT)
    assert exc.value.code == code


def test_validate_rejects_pickup_on_closed_day():
    rules = ShopRules(closed_weekdays=frozenset({3}))  # Thursday 13 May
    with pytest.raises(InvalidDates) as exc:
        validate_rental_dates(RentalDates(date(2027, 5, 13), date(2027, 5, 16)), rules, today=TODAY)
    assert exc.value.code == "pickup_closed"


def test_validate_accepts_derived_dates():
    rules = ShopRules()
    validate_rental_dates(derive_rental_dates(SAT, rules), rules, today=TODAY, event=SAT)


def test_blocked_range_applies_buffers():
    dates = RentalDates(date(2027, 5, 13), date(2027, 5, 16))
    assert blocked_range(dates, prep_days=1, cleaning_days=2) == (date(2027, 5, 12), date(2027, 5, 18))


def test_rules_for_shop_reads_hours_and_closures(db):
    shop = make_shop(db, cleaning_days=2)
    shop.hours.append(ShopHours(weekday=6, closed=True))
    shop.closures.append(ShopClosure(starts_on=date(2027, 8, 1), ends_on=date(2027, 8, 10)))
    db.flush()
    rules = rules_for_shop(shop)
    assert rules.cleaning_days == 2
    assert rules.closed_weekdays == frozenset({6})
    assert rules.closures == ((date(2027, 8, 1), date(2027, 8, 10)),)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.booking'`.

- [ ] **Step 3: Implement clock, errors, dates and rules**

`src/twirl/booking/__init__.py`: empty file.

`src/twirl/clock.py`:

```python
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Belgrade")


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return datetime.now(TZ).date()
```

`src/twirl/booking/errors.py`:

```python
from sqlalchemy.exc import IntegrityError


class BookingError(Exception):
    code = "booking_error"


class InvalidDates(BookingError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InvalidTransition(BookingError):
    code = "invalid_transition"

    def __init__(self, src: str, dst: str) -> None:
        super().__init__(f"{src} -> {dst}")
        self.src = src
        self.dst = dst


class NoAvailability(BookingError):
    code = "no_availability"


class ShopNotBookable(BookingError):
    code = "not_bookable"


class ItemConflict(BookingError):
    code = "item_conflict"

    def __init__(self, conflicts: list, overridable: bool) -> None:
        super().__init__(f"{len(conflicts)} conflicting booking(s)")
        self.conflicts = conflicts
        self.overridable = overridable


def is_exclusion_violation(exc: IntegrityError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == "23P01"
```

`src/twirl/booking/dates.py`:

```python
from dataclasses import dataclass
from datetime import date, timedelta

from twirl.booking.errors import InvalidDates

MAX_ROLL_DAYS = 14


@dataclass(frozen=True)
class ShopRules:
    pickup_lead_days: int = 2
    return_after_days: int = 1
    prep_days: int = 0
    cleaning_days: int = 1
    max_rental_days: int = 7
    closed_weekdays: frozenset[int] = frozenset()
    closures: tuple[tuple[date, date], ...] = ()

    def is_open(self, day: date) -> bool:
        if day.weekday() in self.closed_weekdays:
            return False
        return not any(start <= day <= end for start, end in self.closures)


@dataclass(frozen=True)
class RentalDates:
    pickup: date
    return_: date


def _roll(day: date, step: int, rules: ShopRules) -> date:
    for _ in range(MAX_ROLL_DAYS):
        if rules.is_open(day):
            return day
        day += timedelta(days=step)
    raise InvalidDates("no_open_day")


def derive_rental_dates(event: date, rules: ShopRules) -> RentalDates:
    pickup = _roll(event - timedelta(days=rules.pickup_lead_days), -1, rules)
    return_ = _roll(event + timedelta(days=rules.return_after_days), 1, rules)
    return RentalDates(pickup, return_)


def validate_rental_dates(
    dates: RentalDates, rules: ShopRules, *, today: date, event: date | None = None
) -> None:
    if dates.pickup < today:
        raise InvalidDates("pickup_in_past")
    if dates.return_ < dates.pickup:
        raise InvalidDates("return_before_pickup")
    if (dates.return_ - dates.pickup).days > rules.max_rental_days:
        raise InvalidDates("too_long")
    if event is not None and not dates.pickup <= event <= dates.return_:
        raise InvalidDates("event_outside_rental")
    if not rules.is_open(dates.pickup):
        raise InvalidDates("pickup_closed")
    if not rules.is_open(dates.return_):
        raise InvalidDates("return_closed")


def blocked_range(dates: RentalDates, *, prep_days: int, cleaning_days: int) -> tuple[date, date]:
    return dates.pickup - timedelta(days=prep_days), dates.return_ + timedelta(days=cleaning_days)
```

`src/twirl/booking/rules.py`:

```python
from twirl.booking.dates import ShopRules
from twirl.models import Shop


def rules_for_shop(shop: Shop) -> ShopRules:
    return ShopRules(
        pickup_lead_days=shop.pickup_lead_days,
        return_after_days=shop.return_after_days,
        prep_days=shop.prep_days,
        cleaning_days=shop.cleaning_days,
        max_rental_days=shop.max_rental_days,
        closed_weekdays=frozenset(h.weekday for h in shop.hours if h.closed),
        closures=tuple((c.starts_on, c.ends_on) for c in shop.closures),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dates.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: rental date derivation and validation"
```

---

### Task 6: Booking state machine and timeline

**Files:**
- Create: `src/twirl/booking/actor.py`, `src/twirl/booking/states.py`, `src/twirl/booking/timeline.py`
- Test: `tests/test_timeline.py`

**Interfaces:**
- Consumes: `Booking`, `BookingEvent`, `BookingStatus`, `ActorKind`; `InvalidTransition`, `ItemConflict`, `is_exclusion_violation`.
- Produces: `Actor(kind: ActorKind, id: int | None = None)`, `SYSTEM`; `TRANSITIONS`, `can_transition(src, dst) -> bool`; `record_created(session, booking, actor) -> None`; `transition(session, booking, to, *, actor, reason="") -> Booking`.

- [ ] **Step 1: Write the failing tests**

`tests/test_timeline.py`:

```python
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from tests.factories import make_booking, make_item, make_shop, make_style
from twirl.booking.actor import SYSTEM, Actor
from twirl.booking.errors import InvalidTransition, ItemConflict
from twirl.booking.states import can_transition
from twirl.booking.timeline import record_created, transition
from twirl.models import ActorKind, BookingEvent, BookingStatus

D = date(2027, 6, 1)
SHOP_ACTOR = Actor(ActorKind.SHOP)


def _events(db, booking):
    rows = db.scalars(
        select(BookingEvent).where(BookingEvent.booking_id == booking.id).order_by(BookingEvent.id)
    )
    return [(e.from_status, e.to_status, e.actor_kind, e.reason) for e in rows]


def _item(db):
    return make_item(db, make_style(db, make_shop(db)))


def test_allowed_transition_updates_status_and_logs_event(db):
    booking = make_booking(db, _item(db), pickup=D, return_=D, status="pending_shop", kind="online")
    transition(db, booking, BookingStatus.CONFIRMED, actor=SHOP_ACTOR, reason="ok")
    assert booking.status == "confirmed"
    assert _events(db, booking) == [("pending_shop", "confirmed", "shop", "ok")]


def test_disallowed_transition_raises_and_keeps_status(db):
    booking = make_booking(db, _item(db), pickup=D, return_=D, status="pending_shop", kind="online")
    with pytest.raises(InvalidTransition):
        transition(db, booking, BookingStatus.PICKED_UP, actor=SHOP_ACTOR)
    assert booking.status == "pending_shop"
    assert _events(db, booking) == []


@pytest.mark.parametrize(
    "terminal", ["completed", "declined", "expired", "no_show", "cancelled_by_renter", "cancelled_by_shop"]
)
def test_terminal_statuses_have_no_exits(terminal):
    assert not any(can_transition(BookingStatus(terminal), dst) for dst in BookingStatus)


def test_at_risk_cannot_return_to_confirmed_when_item_is_taken(db):
    item = _item(db)
    at_risk = make_booking(db, item, pickup=D, return_=D + timedelta(2), status="at_risk", kind="online")
    make_booking(db, item, pickup=D, return_=D + timedelta(2), status="confirmed")
    with pytest.raises(ItemConflict):
        transition(db, at_risk, BookingStatus.CONFIRMED, actor=SHOP_ACTOR)
    db.refresh(at_risk)
    assert at_risk.status == "at_risk"


def test_record_created_logs_initial_status(db):
    booking = make_booking(db, _item(db), pickup=D, return_=D)
    record_created(db, booking, SYSTEM)
    db.flush()
    assert _events(db, booking) == [(None, "confirmed", "system", "")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_timeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.booking.actor'`.

- [ ] **Step 3: Implement actor, states and timeline**

`src/twirl/booking/actor.py`:

```python
from dataclasses import dataclass

from twirl.models import ActorKind


@dataclass(frozen=True)
class Actor:
    kind: ActorKind
    id: int | None = None


SYSTEM = Actor(ActorKind.SYSTEM)
```

`src/twirl/booking/states.py`:

```python
from twirl.models import BookingStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.HOLD: frozenset({S.PENDING_SHOP, S.CONFIRMED, S.EXPIRED}),
    S.PENDING_SHOP: frozenset({S.CONFIRMED, S.DECLINED, S.CANCELLED_BY_SHOP, S.CANCELLED_BY_RENTER}),
    S.CONFIRMED: frozenset(
        {S.AT_RISK, S.PICKED_UP, S.NO_SHOW, S.CANCELLED_BY_RENTER, S.CANCELLED_BY_SHOP}
    ),
    S.AT_RISK: frozenset({S.CONFIRMED, S.CANCELLED_BY_SHOP}),
    S.PICKED_UP: frozenset({S.COMPLETED, S.NOT_RETURNED}),
    S.NOT_RETURNED: frozenset({S.COMPLETED}),
}


def can_transition(src: S, dst: S) -> bool:
    return dst in TRANSITIONS.get(src, frozenset())
```

`src/twirl/booking/timeline.py`:

```python
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from twirl.booking.actor import Actor
from twirl.booking.errors import InvalidTransition, ItemConflict, is_exclusion_violation
from twirl.booking.states import can_transition
from twirl.models import Booking, BookingEvent, BookingStatus


def record_created(session: Session, booking: Booking, actor: Actor) -> None:
    session.add(
        BookingEvent(
            booking_id=booking.id, from_status=None, to_status=booking.status,
            actor_id=actor.id, actor_kind=actor.kind.value, reason="",
        )
    )


def transition(
    session: Session, booking: Booking, to: BookingStatus, *, actor: Actor, reason: str = ""
) -> Booking:
    src = BookingStatus(booking.status)
    if not can_transition(src, to):
        raise InvalidTransition(src.value, to.value)
    try:
        with session.begin_nested():
            booking.status = to.value
            if reason:
                booking.reason = reason
            session.add(
                BookingEvent(
                    booking_id=booking.id, from_status=src.value, to_status=to.value,
                    actor_id=actor.id, actor_kind=actor.kind.value, reason=reason,
                )
            )
            session.flush()
    except IntegrityError as exc:
        if is_exclusion_violation(exc):
            raise ItemConflict([], overridable=False) from exc
        raise
    return booking
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_timeline.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: booking state machine with append-only timeline"
```

---

### Task 7: Notification outbox

**Files:**
- Create: `src/twirl/models/notifications.py`, `src/twirl/notify/__init__.py`, `src/twirl/notify/templates.py`, `src/twirl/notify/outbox.py`, `src/twirl/notify/payloads.py`
- Modify: `src/twirl/models/__init__.py`
- Create: `migrations/versions/0004_notifications.py` (autogenerated)
- Test: `tests/test_outbox.py`

**Interfaces:**
- Consumes: `Booking`, `ShopUser`, `User`.
- Produces: `Notification`, `Channel`, `NotificationStatus`; `ADMIN_RECIPIENT = "admin"`, `TEMPLATES`, `render(template, payload, *, base_url="") -> tuple[str, str]`; `enqueue(session, *, channel, recipient, template, payload) -> Notification`, `notify_admin(session, template, payload) -> Notification`, `notify_shop_owners(session, shop_id, template, payload) -> list[Notification]`; `fmt_date(d) -> str`, `booking_payload(booking) -> dict`.

- [ ] **Step 1: Write the failing tests**

`tests/test_outbox.py`:

```python
from datetime import date

import pytest

from tests.factories import make_booking, make_item, make_renter, make_shop, make_shop_user, make_style
from twirl.models import Channel, Notification
from twirl.notify.outbox import enqueue, notify_admin, notify_shop_owners
from twirl.notify.payloads import booking_payload
from twirl.notify.templates import TEMPLATES, render


def test_notify_shop_owners_emails_owners_only(db):
    shop = make_shop(db)
    owner = make_shop_user(db, shop, role="owner")
    make_shop_user(db, shop, role="staff")
    rows = notify_shop_owners(db, shop.id, "new_request_shop", {"ref": "X"})
    db.flush()
    assert [(n.channel, n.recipient, n.status) for n in rows] == [("email", owner.email, "queued")]


def test_notify_admin_targets_admin_telegram(db):
    row = notify_admin(db, "new_request_admin", {"ref": "X"})
    db.flush()
    stored = db.get(Notification, row.id)
    assert (stored.channel, stored.recipient) == ("telegram", "admin")


def test_enqueue_rejects_unknown_template(db):
    with pytest.raises(KeyError):
        enqueue(db, channel=Channel.EMAIL, recipient="a@b.c", template="nope", payload={})


def test_booking_payload_and_every_template_render(db):
    shop = make_shop(db, name="Bella")
    style = make_style(db, shop, name="Red gown")
    item = make_item(db, style, size="38")
    booking = make_booking(
        db, item, pickup=date(2027, 5, 13), return_=date(2027, 5, 16), kind="online",
        status="pending_shop", customer=make_renter(db, name="Arta"), event_date=date(2027, 5, 15),
    )
    payload = booking_payload(booking)
    assert payload["pickup_date"] == "13.05.2027"
    assert payload["shop_name"] == "Bella"
    assert payload["customer_name"] == "Arta"
    assert payload["path"] == f"/shop/bookings/{booking.id}"
    for name in TEMPLATES:
        subject, body = render(name, {**payload, "reason": "r", "hours": 24}, base_url="https://twirl.test")
        assert booking.ref in subject + body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_outbox.py -v`
Expected: FAIL with `ImportError: cannot import name 'Notification'`.

- [ ] **Step 3: Implement model, templates, outbox and payloads**

`src/twirl/models/notifications.py`:

```python
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from twirl.models.base import Base, Timestamps, check_in


class Channel(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"


class NotificationStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class Notification(Timestamps, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        check_in("channel", Channel),
        check_in("status", NotificationStatus),
        Index("ix_notifications_queued", "id", postgresql_where=text("status = 'queued'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(16))
    recipient: Mapped[str] = mapped_column(String(254))
    template: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(
        String(16), default=NotificationStatus.QUEUED.value, server_default=text("'queued'")
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    last_error: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    provider_id: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Add to `src/twirl/models/__init__.py` (import line and the three names in `__all__`):

```python
from twirl.models.notifications import Channel, Notification, NotificationStatus
```

`src/twirl/notify/__init__.py`: empty file.

`src/twirl/notify/templates.py` (shop-facing text is Albanian, admin-facing text is English; the founder proofreads the Albanian):

```python
from collections.abc import Callable

ADMIN_RECIPIENT = "admin"

Rendered = tuple[str, str]


def _new_request_shop(p: dict, base_url: str) -> Rendered:
    pending = p.get("status") == "pending_shop"
    subject = f"Kërkesë e re: {p['style_name']}, masa {p['size']} ({p['ref']})"
    lines = [
        "Keni një kërkesë të re për rezervim në Twirl." if pending
        else "Keni një rezervim të ri në Twirl.",
        "",
        f"Fustani: {p['style_name']} ({p['style_code']}), masa {p['size']}, kodi {p['item_code']}",
        f"Data e eventit: {p['event_date']}",
        f"Marrja: {p['pickup_date']} · Kthimi: {p['return_date']}",
        f"Klienti: {p['customer_name']}, {p['customer_phone']}",
        f"Kodi i rezervimit: {p['ref']}",
        "",
        f"Hapeni këtu: {base_url}{p['path']}",
    ]
    if pending:
        lines.append("Nëse nuk përgjigjeni brenda 24 orësh, kërkesa anulohet automatikisht.")
    return subject, "\n".join(lines)


def _new_request_admin(p: dict, base_url: str) -> Rendered:
    return "", (
        f"New {p['status']} booking {p['ref']} at {p['shop_name']}: {p['style_name']} "
        f"size {p['size']}, event {p['event_date']}. {base_url}/admin/booking/list?search={p['ref']}"
    )


def _booking_at_risk_admin(p: dict, base_url: str) -> Rendered:
    return "", (
        f"AT RISK {p['ref']} at {p['shop_name']}: dress {p['item_code']} ({p['style_name']} "
        f"{p['size']}) was taken in store. Reason: {p['reason']}. "
        f"Renter: {p['customer_name']} {p['customer_phone']}. "
        f"{base_url}/admin/booking/list?search={p['ref']}"
    )


def _request_expired_admin(p: dict, base_url: str) -> Rendered:
    return "", (
        f"Request {p['ref']} at {p['shop_name']} was auto-cancelled after {p['hours']} h "
        f"with no reply. Renter: {p['customer_name']} {p['customer_phone']}."
    )


TEMPLATES: dict[str, Callable[[dict, str], Rendered]] = {
    "new_request_shop": _new_request_shop,
    "new_request_admin": _new_request_admin,
    "booking_at_risk_admin": _booking_at_risk_admin,
    "request_expired_admin": _request_expired_admin,
}


def render(template: str, payload: dict, *, base_url: str = "") -> Rendered:
    return TEMPLATES[template](payload, base_url)
```

`src/twirl/notify/outbox.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl.models import Channel, Notification, ShopRole, ShopUser, User
from twirl.notify.templates import ADMIN_RECIPIENT, TEMPLATES


def enqueue(
    session: Session, *, channel: Channel, recipient: str, template: str, payload: dict
) -> Notification:
    if template not in TEMPLATES:
        raise KeyError(template)
    notification = Notification(
        channel=channel.value, recipient=recipient, template=template, payload=payload
    )
    session.add(notification)
    return notification


def notify_admin(session: Session, template: str, payload: dict) -> Notification:
    return enqueue(
        session, channel=Channel.TELEGRAM, recipient=ADMIN_RECIPIENT, template=template,
        payload=payload,
    )


def notify_shop_owners(
    session: Session, shop_id: int, template: str, payload: dict
) -> list[Notification]:
    emails = session.scalars(
        select(User.email)
        .join(ShopUser, ShopUser.user_id == User.id)
        .where(
            ShopUser.shop_id == shop_id,
            ShopUser.role == ShopRole.OWNER.value,
            User.email.is_not(None),
        )
        .order_by(User.id)
    ).all()
    return [
        enqueue(session, channel=Channel.EMAIL, recipient=email, template=template, payload=payload)
        for email in emails
    ]
```

`src/twirl/notify/payloads.py`:

```python
from datetime import date

from twirl.models import Booking


def fmt_date(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def booking_payload(booking: Booking) -> dict:
    customer = booking.customer
    return {
        "ref": booking.ref,
        "status": booking.status,
        "shop_name": booking.shop.name,
        "style_name": booking.style.name,
        "style_code": booking.style.code,
        "size": booking.item.size,
        "item_code": booking.item.code,
        "event_date": fmt_date(booking.event_date),
        "pickup_date": fmt_date(booking.pickup_date),
        "return_date": fmt_date(booking.return_date),
        "customer_name": customer.name if customer else "",
        "customer_phone": customer.phone if customer and customer.phone else "",
        "path": f"/shop/bookings/{booking.id}",
    }
```

- [ ] **Step 4: Generate and apply the migration**

```bash
uv run alembic revision --autogenerate --rev-id 0004 -m "notifications"
uv run alembic upgrade head
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_outbox.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: notification outbox with shop and admin templates"
```

---

### Task 8: Availability and storefront requests, with the concurrency guarantee

**Files:**
- Create: `src/twirl/phones.py`, `src/twirl/customers.py`, `src/twirl/booking/availability.py`, `src/twirl/booking/requests.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_phones.py`, `tests/test_requests.py`, `tests/test_concurrency.py`

**Interfaces:**
- Consumes: date rules (Task 5), `transition`/`record_created`/`Actor` (Task 6), outbox + `booking_payload` (Task 7), `new_booking_ref`, `normalize_size`, `size_sort_key`.
- Produces: `InvalidPhone(ValueError)`, `normalize_phone(raw, region="XK") -> str`; `get_or_create_customer(session, *, phone, name) -> User`, `link_customer(session, *, shop_id, user_id) -> None`; `overlapping_bookings(session, item_id, start, end) -> list[Booking]`, `free_items_stmt(*, start, end, style_id=None, shop_id=None, size=None) -> Select`, `StyleAvailability(dates, sizes: dict[str, bool])`, `style_availability(session, style, event_date, *, today) -> StyleAvailability`; `RentalRequest(style_id, size, event_date, name, phone, note="")`, `create_request(session, req, *, today, max_attempts=3) -> Booking`; pytest fixture `committed`.

- [ ] **Step 1: Write the failing tests**

`tests/test_phones.py`:

```python
import pytest

from twirl.phones import InvalidPhone, normalize_phone


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("044 123 456", "+38344123456"),
        ("+383 49 123 456", "+38349123456"),
        ("00383 45 123 456", "+38345123456"),
        ("+49 151 23456789", "+4915123456789"),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "123", "044 12"])
def test_normalize_phone_rejects_garbage(raw):
    with pytest.raises(InvalidPhone):
        normalize_phone(raw)
```

Append to `tests/conftest.py`:

```python
from twirl.models import Base  # noqa: E402


@pytest.fixture
def committed(engine):
    """For tests that need real commits across connections. Truncates everything afterwards."""
    yield engine
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
```

`tests/test_requests.py`:

```python
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from tests.factories import make_booking, make_item, make_shop, make_shop_user, make_style
from twirl import clock
from twirl.booking.availability import style_availability
from twirl.booking.dates import derive_rental_dates
from twirl.booking.errors import InvalidDates, NoAvailability, ShopNotBookable
from twirl.booking.requests import RentalRequest, create_request
from twirl.booking.rules import rules_for_shop
from twirl.models import BookingEvent, Notification, ShopCustomer, User

EVENT = clock.today() + timedelta(days=30)


def _req(style, **kw):
    return RentalRequest(
        style_id=style.id, size=kw.pop("size", "38"), event_date=kw.pop("event_date", EVENT),
        name=kw.pop("name", "Arta"), phone=kw.pop("phone", "044 123 456"), **kw,
    )


def _setup(db, **shop_kw):
    shop = make_shop(db, **shop_kw)
    make_shop_user(db, shop, role="owner")
    style = make_style(db, shop)
    return shop, style


def test_request_mode_creates_pending_booking_event_and_notifications(db):
    _, style = _setup(db)
    item = make_item(db, style, size="38")
    booking = create_request(db, _req(style), today=clock.today())
    assert (booking.status, booking.kind, booking.item_id) == ("pending_shop", "online", item.id)
    assert booking.price_cents == style.price_cents
    events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == booking.id)).all()
    assert [(e.from_status, e.to_status, e.actor_kind) for e in events] == [(None, "pending_shop", "renter")]
    assert sorted(n.channel for n in db.scalars(select(Notification))) == ["email", "telegram"]


def test_instant_mode_confirms_immediately(db):
    _, style = _setup(db, booking_mode="instant")
    make_item(db, style)
    assert create_request(db, _req(style), today=clock.today()).status == "confirmed"


def test_second_request_gets_the_second_dress(db):
    _, style = _setup(db)
    first, second = make_item(db, style), make_item(db, style)
    a = create_request(db, _req(style), today=clock.today())
    b = create_request(db, _req(style, phone="044 999 888"), today=clock.today())
    assert (a.item_id, b.item_id) == (first.id, second.id)


def test_no_free_dress_raises(db):
    shop, style = _setup(db)
    item = make_item(db, style)
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, item, pickup=dates.pickup, return_=dates.return_)
    with pytest.raises(NoAvailability):
        create_request(db, _req(style), today=clock.today())


def test_other_size_is_not_offered(db):
    _, style = _setup(db)
    make_item(db, style, size="40")
    with pytest.raises(NoAvailability):
        create_request(db, _req(style, size="38"), today=clock.today())


@pytest.mark.parametrize("shop_status, published", [("draft", True), ("published", False)])
def test_unpublished_shop_or_style_is_not_bookable(db, shop_status, published):
    shop = make_shop(db, status=shop_status)
    style = make_style(db, shop, published=published)
    make_item(db, style)
    with pytest.raises(ShopNotBookable):
        create_request(db, _req(style), today=clock.today())


def test_event_too_soon_is_rejected(db):
    _, style = _setup(db)
    make_item(db, style)
    with pytest.raises(InvalidDates) as exc:
        create_request(db, _req(style, event_date=clock.today()), today=clock.today())
    assert exc.value.code == "pickup_in_past"


def test_same_phone_reuses_renter_and_links_shop_once(db):
    shop, style = _setup(db)
    make_item(db, style)
    make_item(db, style)
    create_request(db, _req(style), today=clock.today())
    create_request(db, _req(style, name="Arta B."), today=clock.today())
    assert db.scalar(select(func.count()).select_from(User).where(User.phone == "+38344123456")) == 1
    assert db.scalar(select(func.count()).select_from(ShopCustomer).where(ShopCustomer.shop_id == shop.id)) == 1


def test_style_availability_reports_each_size(db):
    shop, style = _setup(db)
    taken = make_item(db, style, size="38")
    make_item(db, style, size="40")
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, taken, pickup=dates.pickup, return_=dates.return_)
    availability = style_availability(db, style, EVENT, today=clock.today())
    assert availability.dates == dates
    assert availability.sizes == {"38": False, "40": True}
    assert list(availability.sizes) == ["38", "40"]
```

`tests/test_concurrency.py`:

```python
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from tests.factories import make_item, make_shop, make_style
from twirl import clock
from twirl.booking.errors import NoAvailability
from twirl.booking.requests import RentalRequest, create_request
from twirl.models import Booking


@pytest.mark.parametrize("dresses", [1, 2])
def test_fifty_parallel_requests_never_double_book(committed, dresses):
    make_session = sessionmaker(committed, expire_on_commit=False)
    with make_session() as s:
        style = make_style(s, make_shop(s))
        for _ in range(dresses):
            make_item(s, style, size="38")
        s.commit()
        style_id = style.id
    event = clock.today() + timedelta(days=30)

    def attempt(i: int) -> str:
        with make_session() as s:
            try:
                create_request(
                    s,
                    RentalRequest(
                        style_id=style_id, size="38", event_date=event, name=f"R{i}",
                        phone=f"+3834912{i:04d}",
                    ),
                    today=clock.today(),
                )
                s.commit()
                return "ok"
            except NoAvailability:
                s.rollback()
                return "none"

    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(attempt, range(50)))

    assert results.count("ok") == dresses
    assert results.count("none") == 50 - dresses
    with make_session() as s:
        assert s.scalar(select(func.count()).select_from(Booking)) == dresses
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_phones.py tests/test_requests.py tests/test_concurrency.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.phones'`.

- [ ] **Step 3: Implement phones and customers**

`src/twirl/phones.py`:

```python
import phonenumbers


class InvalidPhone(ValueError):
    pass


def normalize_phone(raw: str, region: str = "XK") -> str:
    try:
        parsed = phonenumbers.parse(raw.strip(), region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhone(raw) from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhone(raw)
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
```

`src/twirl/customers.py`:

```python
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from twirl.models import ShopCustomer, User, UserKind


def get_or_create_customer(session: Session, *, phone: str, name: str) -> User:
    session.execute(
        pg_insert(User)
        .values(kind=UserKind.RENTER.value, name=name.strip()[:120], phone=phone)
        .on_conflict_do_nothing(index_elements=["phone"])
    )
    return session.scalars(select(User).where(User.phone == phone)).one()


def link_customer(session: Session, *, shop_id: int, user_id: int) -> None:
    session.execute(
        pg_insert(ShopCustomer)
        .values(shop_id=shop_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["shop_id", "user_id"])
    )
```

- [ ] **Step 4: Implement availability**

`src/twirl/booking/availability.py`:

```python
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from twirl.booking.dates import RentalDates, blocked_range, derive_rental_dates, validate_rental_dates
from twirl.booking.rules import rules_for_shop
from twirl.catalog import size_sort_key
from twirl.models import ACTIVE_STATUSES, Booking, Item, ItemStatus, Style


def _range(start: date, end: date) -> Range[date]:
    return Range(start, end, bounds="[]")


def overlapping_bookings(session: Session, item_id: int, start: date, end: date) -> list[Booking]:
    return list(
        session.scalars(
            select(Booking)
            .where(
                Booking.item_id == item_id,
                Booking.status.in_(ACTIVE_STATUSES),
                Booking.blocked_range.overlaps(_range(start, end)),
            )
            .order_by(Booking.pickup_date)
        )
    )


def free_items_stmt(
    *, start: date, end: date, style_id: int | None = None, shop_id: int | None = None,
    size: str | None = None,
) -> Select:
    busy = (
        select(Booking.id)
        .where(
            Booking.item_id == Item.id,
            Booking.status.in_(ACTIVE_STATUSES),
            Booking.blocked_range.overlaps(_range(start, end)),
        )
        .exists()
    )
    stmt = select(Item).where(Item.status == ItemStatus.ACTIVE.value, ~busy)
    if style_id is not None:
        stmt = stmt.where(Item.style_id == style_id)
    if shop_id is not None:
        stmt = stmt.where(Item.shop_id == shop_id)
    if size is not None:
        stmt = stmt.where(Item.size == size)
    return stmt


@dataclass(frozen=True)
class StyleAvailability:
    dates: RentalDates
    sizes: dict[str, bool]


def style_availability(
    session: Session, style: Style, event_date: date, *, today: date
) -> StyleAvailability:
    rules = rules_for_shop(style.shop)
    dates = derive_rental_dates(event_date, rules)
    validate_rental_dates(dates, rules, today=today, event=event_date)
    start, end = blocked_range(dates, prep_days=rules.prep_days, cleaning_days=rules.cleaning_days)
    all_sizes = set(
        session.scalars(
            select(Item.size).where(
                Item.style_id == style.id, Item.status == ItemStatus.ACTIVE.value
            )
        )
    )
    free_sizes = set(
        session.scalars(
            free_items_stmt(start=start, end=end, style_id=style.id).with_only_columns(Item.size)
        )
    )
    ordered = sorted(all_sizes, key=size_sort_key)
    return StyleAvailability(dates=dates, sizes={s: s in free_sizes for s in ordered})
```

- [ ] **Step 5: Implement create_request**

`src/twirl/booking/requests.py`:

```python
from dataclasses import dataclass
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from twirl.booking.actor import Actor
from twirl.booking.availability import free_items_stmt
from twirl.booking.dates import blocked_range, derive_rental_dates, validate_rental_dates
from twirl.booking.errors import NoAvailability, ShopNotBookable, is_exclusion_violation
from twirl.booking.rules import rules_for_shop
from twirl.booking.timeline import record_created
from twirl.catalog import normalize_size
from twirl.codes import new_booking_ref
from twirl.customers import get_or_create_customer, link_customer
from twirl.models import (
    ActorKind, Booking, BookingKind, BookingMode, BookingStatus, Item, ShopStatus, Style,
)
from twirl.notify.outbox import notify_admin, notify_shop_owners
from twirl.notify.payloads import booking_payload
from twirl.phones import normalize_phone


@dataclass(frozen=True)
class RentalRequest:
    style_id: int
    size: str
    event_date: date
    name: str
    phone: str
    note: str = ""


def create_request(
    session: Session, req: RentalRequest, *, today: date, max_attempts: int = 3
) -> Booking:
    style = session.get(Style, req.style_id)
    if style is None or not style.published or style.deleted_at is not None:
        raise ShopNotBookable()
    shop = style.shop
    if shop.status != ShopStatus.PUBLISHED.value:
        raise ShopNotBookable()

    rules = rules_for_shop(shop)
    dates = derive_rental_dates(req.event_date, rules)
    validate_rental_dates(dates, rules, today=today, event=req.event_date)
    start, end = blocked_range(dates, prep_days=rules.prep_days, cleaning_days=rules.cleaning_days)
    size = normalize_size(req.size)
    phone = normalize_phone(req.phone)
    customer = get_or_create_customer(session, phone=phone, name=req.name)
    status = (
        BookingStatus.CONFIRMED
        if shop.booking_mode == BookingMode.INSTANT.value
        else BookingStatus.PENDING_SHOP
    )

    for _ in range(max_attempts):
        item_id = session.scalar(
            free_items_stmt(start=start, end=end, style_id=style.id, size=size)
            .with_only_columns(Item.id)
            .order_by(Item.id)
            .limit(1)
            .with_for_update(skip_locked=True, of=Item)
        )
        if item_id is None:
            raise NoAvailability()
        booking = Booking(
            ref=new_booking_ref(session),
            shop_id=shop.id,
            style_id=style.id,
            item_id=item_id,
            customer_id=customer.id,
            kind=BookingKind.ONLINE.value,
            status=status.value,
            event_date=req.event_date,
            pickup_date=dates.pickup,
            return_date=dates.return_,
            prep_days=rules.prep_days,
            cleaning_days=rules.cleaning_days,
            source_channel="storefront",
            price_cents=style.price_cents,
            fee_cents=0,
            customer_note=req.note.strip()[:500],
        )
        try:
            with session.begin_nested():
                session.add(booking)
                session.flush()
        except IntegrityError as exc:
            if is_exclusion_violation(exc):
                continue
            raise
        record_created(session, booking, Actor(ActorKind.RENTER, customer.id))
        link_customer(session, shop_id=shop.id, user_id=customer.id)
        payload = booking_payload(booking)
        notify_shop_owners(session, shop.id, "new_request_shop", payload)
        notify_admin(session, "new_request_admin", payload)
        session.flush()
        return booking
    raise NoAvailability()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_phones.py tests/test_requests.py tests/test_concurrency.py -v`
Expected: all pass. If a phone fixture number is rejected as invalid by the installed `phonenumbers` metadata, replace it with another number from the same Kosovo mobile range (043, 044, 045, 048, 049) rather than loosening the validity check.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: storefront booking requests with SKIP LOCKED item selection"
```

---

### Task 9: Staff operations — walk-ins with override, blocks, swaps, lifecycle

**Files:**
- Create: `src/twirl/booking/staff.py`
- Test: `tests/test_staff.py`

**Interfaces:**
- Consumes: everything from Tasks 5–8.
- Produces:
  - `find_item_by_code(session, shop_id, code) -> Item | None`
  - `create_staff_booking(session, *, shop, item, pickup, return_, name, phone, actor, kind=BookingKind.WALK_IN, picked_up_now=False, override_reason=None, note="") -> Booking`
  - `create_block(session, *, item, starts_on, ends_on, reason, actor) -> Booking`
  - `cancel_block(session, booking, actor) -> Booking`
  - `swap_candidates(session, booking, limit=20) -> list[Item]`
  - `swap_item(session, booking, new_item, *, actor) -> Booking`
  - `accept(session, booking, actor)`, `decline(session, booking, actor, reason)`, `mark_picked_up(session, booking, actor)`, `mark_returned(session, booking, actor, *, ok, note="")`, `mark_no_show(session, booking, actor)`, `cancel_by_shop(session, booking, actor, reason)` — each returns the `Booking`
  - `set_item_status(session, item, status, *, actor, today, note="") -> list[Booking]` (active bookings ending on or after `today`)

- [ ] **Step 1: Write the failing tests**

`tests/test_staff.py`:

```python
from datetime import timedelta

import pytest
from sqlalchemy import select

from tests.factories import make_booking, make_item, make_renter, make_shop, make_style
from twirl import clock
from twirl.booking.actor import Actor
from twirl.booking.errors import ItemConflict
from twirl.booking.staff import (
    cancel_block, create_block, create_staff_booking, decline, mark_returned, set_item_status,
    swap_candidates, swap_item,
)
from twirl.models import ActorKind, BookingEvent, ItemConditionEvent, Notification, ShopCustomer

PICK = clock.today() + timedelta(days=10)
RET = PICK + timedelta(days=2)
STAFF = Actor(ActorKind.SHOP)


def _setup(db):
    shop = make_shop(db)
    style = make_style(db, shop)
    return shop, style, make_item(db, style, size="38")


def _walk_in(db, shop, item, **kw):
    return create_staff_booking(
        db, shop=shop, item=item, pickup=kw.pop("pickup", PICK), return_=kw.pop("return_", RET),
        name="Blerta", phone="044 555 666", actor=STAFF, **kw,
    )


def test_walk_in_without_conflict_is_confirmed(db):
    shop, _, item = _setup(db)
    booking = _walk_in(db, shop, item)
    assert (booking.status, booking.kind, booking.customer.phone) == ("confirmed", "walk_in", "+38344555666")
    link = db.scalar(select(ShopCustomer).where(ShopCustomer.shop_id == shop.id))
    assert link.user_id == booking.customer_id


def test_walk_in_picked_up_now_goes_straight_to_picked_up(db):
    shop, _, item = _setup(db)
    booking = _walk_in(db, shop, item, picked_up_now=True)
    assert booking.status == "picked_up"
    events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == booking.id).order_by(BookingEvent.id))
    assert [(e.from_status, e.to_status) for e in events] == [(None, "confirmed"), ("confirmed", "picked_up")]


def test_conflict_with_online_booking_requires_a_reason(db):
    shop, _, item = _setup(db)
    online = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="confirmed")
    with pytest.raises(ItemConflict) as exc:
        _walk_in(db, shop, item)
    assert exc.value.overridable
    assert [b.id for b in exc.value.conflicts] == [online.id]


def test_override_flags_online_booking_at_risk_and_alerts_admin(db):
    shop, _, item = _setup(db)
    online = make_booking(
        db, item, pickup=PICK, return_=RET, kind="online", status="confirmed", customer=make_renter(db)
    )
    walk_in = _walk_in(db, shop, item, override_reason="customer paid cash")
    db.refresh(online)
    assert (online.status, walk_in.status) == ("at_risk", "confirmed")
    alert = db.scalars(select(Notification).where(Notification.template == "booking_at_risk_admin")).one()
    assert alert.payload["ref"] == online.ref
    assert alert.payload["reason"] == "customer paid cash"


def test_override_declines_a_pending_request(db):
    shop, _, item = _setup(db)
    pending = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="pending_shop")
    _walk_in(db, shop, item, override_reason="walk-in")
    db.refresh(pending)
    assert pending.status == "declined"


def test_staff_booking_cannot_be_overridden(db):
    shop, _, item = _setup(db)
    make_booking(db, item, pickup=PICK, return_=RET, kind="walk_in", status="confirmed")
    with pytest.raises(ItemConflict) as exc:
        _walk_in(db, shop, item, override_reason="please")
    assert not exc.value.overridable


def test_block_prevents_bookings_until_cancelled(db):
    shop, _, item = _setup(db)
    block = create_block(db, item=item, starts_on=PICK, ends_on=RET, reason="repair", actor=STAFF)
    assert (block.kind, block.customer_id, block.cleaning_days) == ("block", None, 0)
    with pytest.raises(ItemConflict) as exc:
        _walk_in(db, shop, item, override_reason="x")
    assert not exc.value.overridable
    cancel_block(db, block, STAFF)
    assert _walk_in(db, shop, item).status == "confirmed"


def test_swap_at_risk_booking_to_free_item_confirms_it(db):
    _, style, item = _setup(db)
    other = make_item(db, style, size="38")
    online = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="at_risk")
    swap_item(db, online, other, actor=STAFF)
    db.refresh(online)
    assert (online.item_id, online.status) == (other.id, "confirmed")
    last = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == online.id).order_by(BookingEvent.id.desc())).first()
    assert last.reason == f"swap {item.code} -> {other.code}"


def test_swap_to_busy_item_raises_and_changes_nothing(db):
    shop, style, item = _setup(db)
    other = make_item(db, style, size="38")
    make_booking(db, other, pickup=PICK, return_=RET, kind="walk_in")
    online = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="confirmed")
    with pytest.raises(ItemConflict):
        swap_item(db, online, other, actor=STAFF)
    db.refresh(online)
    assert online.item_id == item.id


def test_swap_candidates_prefer_same_style_then_same_size(db):
    shop, style, item = _setup(db)
    same = make_item(db, style, size="38")
    other_size = make_item(db, style, size="40")
    other_style = make_item(db, make_style(db, shop), size="38")
    booking = make_booking(db, item, pickup=PICK, return_=RET)
    assert [i.id for i in swap_candidates(db, booking)] == [same.id, other_size.id, other_style.id]


def test_return_with_issue_logs_condition(db):
    _, _, item = _setup(db)
    booking = make_booking(db, item, pickup=PICK, return_=RET, status="picked_up")
    mark_returned(db, booking, STAFF, ok=False, note="stain on hem")
    assert booking.status == "completed"
    event = db.scalars(select(ItemConditionEvent)).one()
    assert (event.kind, event.note, event.booking_id) == ("returned_issue", "stain on hem", booking.id)


def test_decline_requires_a_reason(db):
    _, _, item = _setup(db)
    booking = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="pending_shop")
    with pytest.raises(ValueError):
        decline(db, booking, STAFF, "   ")


def test_set_item_status_returns_future_bookings(db):
    _, _, item = _setup(db)
    booking = make_booking(db, item, pickup=PICK, return_=RET)
    future = set_item_status(db, item, "repair", actor=STAFF, today=clock.today())
    assert item.status == "repair"
    assert [b.id for b in future] == [booking.id]
    assert db.scalars(select(ItemConditionEvent)).one().kind == "status_change"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_staff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.booking.staff'`.

- [ ] **Step 3: Implement staff operations**

`src/twirl/booking/staff.py`:

```python
from datetime import date, timedelta

from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from twirl.booking.actor import Actor
from twirl.booking.availability import free_items_stmt, overlapping_bookings
from twirl.booking.dates import RentalDates, blocked_range
from twirl.booking.errors import InvalidDates, InvalidTransition, ItemConflict, is_exclusion_violation
from twirl.booking.timeline import record_created, transition
from twirl.codes import new_booking_ref
from twirl.customers import get_or_create_customer, link_customer
from twirl.models import (
    ACTIVE_STATUSES, Booking, BookingEvent, BookingKind, BookingStatus, ConditionKind, Item,
    ItemConditionEvent, ItemStatus, Shop,
)
from twirl.notify.outbox import notify_admin
from twirl.notify.payloads import booking_payload
from twirl.phones import normalize_phone

MAX_STAFF_RENTAL_DAYS = 30
OVERRIDABLE = {BookingStatus.PENDING_SHOP.value, BookingStatus.CONFIRMED.value}
SWAPPABLE = {
    BookingStatus.PENDING_SHOP.value, BookingStatus.CONFIRMED.value, BookingStatus.AT_RISK.value,
}


def find_item_by_code(session: Session, shop_id: int, code: str) -> Item | None:
    return session.scalar(
        select(Item).where(Item.shop_id == shop_id, Item.code == code.strip().upper())
    )


def _insert(session: Session, booking: Booking, start: date, end: date) -> None:
    try:
        with session.begin_nested():
            session.add(booking)
            session.flush()
    except IntegrityError as exc:
        if is_exclusion_violation(exc):
            raise ItemConflict(
                overlapping_bookings(session, booking.item_id, start, end), overridable=False
            ) from exc
        raise


def create_staff_booking(
    session: Session,
    *,
    shop: Shop,
    item: Item,
    pickup: date,
    return_: date,
    name: str,
    phone: str,
    actor: Actor,
    kind: BookingKind = BookingKind.WALK_IN,
    picked_up_now: bool = False,
    override_reason: str | None = None,
    note: str = "",
) -> Booking:
    if item.shop_id != shop.id:
        raise ValueError("item belongs to another shop")
    if return_ < pickup:
        raise InvalidDates("return_before_pickup")
    if (return_ - pickup).days > MAX_STAFF_RENTAL_DAYS:
        raise InvalidDates("too_long")
    phone_e164 = normalize_phone(phone)
    start, end = blocked_range(
        RentalDates(pickup, return_), prep_days=shop.prep_days, cleaning_days=shop.cleaning_days
    )

    conflicts = overlapping_bookings(session, item.id, start, end)
    if conflicts:
        overridable = all(
            c.kind == BookingKind.ONLINE.value and c.status in OVERRIDABLE for c in conflicts
        )
        reason = (override_reason or "").strip()
        if not overridable or not reason:
            raise ItemConflict(conflicts, overridable=overridable)
        for conflict in conflicts:
            if conflict.status == BookingStatus.PENDING_SHOP.value:
                transition(session, conflict, BookingStatus.DECLINED, actor=actor,
                           reason=f"item taken in store: {reason}")
            else:
                transition(session, conflict, BookingStatus.AT_RISK, actor=actor,
                           reason=f"item taken in store: {reason}")
                notify_admin(
                    session, "booking_at_risk_admin", {**booking_payload(conflict), "reason": reason}
                )

    customer = get_or_create_customer(session, phone=phone_e164, name=name)
    booking = Booking(
        ref=new_booking_ref(session),
        shop_id=shop.id,
        style_id=item.style_id,
        item_id=item.id,
        customer_id=customer.id,
        kind=kind.value,
        status=BookingStatus.CONFIRMED.value,
        pickup_date=pickup,
        return_date=return_,
        prep_days=shop.prep_days,
        cleaning_days=shop.cleaning_days,
        source_channel="staff",
        price_cents=item.style.price_cents,
        staff_note=note.strip()[:500],
        created_by=actor.id,
    )
    _insert(session, booking, start, end)
    record_created(session, booking, actor)
    link_customer(session, shop_id=shop.id, user_id=customer.id)
    if picked_up_now:
        transition(session, booking, BookingStatus.PICKED_UP, actor=actor)
    return booking


def create_block(
    session: Session, *, item: Item, starts_on: date, ends_on: date, reason: str, actor: Actor
) -> Booking:
    if ends_on < starts_on:
        raise InvalidDates("return_before_pickup")
    conflicts = overlapping_bookings(session, item.id, starts_on, ends_on)
    if conflicts:
        raise ItemConflict(conflicts, overridable=False)
    block = Booking(
        ref=new_booking_ref(session),
        shop_id=item.shop_id,
        style_id=item.style_id,
        item_id=item.id,
        kind=BookingKind.BLOCK.value,
        status=BookingStatus.CONFIRMED.value,
        pickup_date=starts_on,
        return_date=ends_on,
        prep_days=0,
        cleaning_days=0,
        source_channel="staff",
        reason=reason.strip()[:300],
        created_by=actor.id,
    )
    _insert(session, block, starts_on, ends_on)
    record_created(session, block, actor)
    return block


def cancel_block(session: Session, booking: Booking, actor: Actor) -> Booking:
    if booking.kind != BookingKind.BLOCK.value:
        raise ValueError("not a block")
    return transition(session, booking, BookingStatus.CANCELLED_BY_SHOP, actor=actor, reason="block removed")


def swap_candidates(session: Session, booking: Booking, limit: int = 20) -> list[Item]:
    start = booking.blocked_range.lower
    end = booking.blocked_range.upper - timedelta(days=1)
    stmt = (
        free_items_stmt(start=start, end=end, shop_id=booking.shop_id)
        .where(Item.id != booking.item_id)
        .order_by(
            case((Item.style_id == booking.style_id, 0), else_=1),
            case((Item.size == booking.item.size, 0), else_=1),
            Item.id,
        )
        .limit(limit)
    )
    return list(session.scalars(stmt))


def swap_item(session: Session, booking: Booking, new_item: Item, *, actor: Actor) -> Booking:
    if new_item.shop_id != booking.shop_id or new_item.status != ItemStatus.ACTIVE.value:
        raise ValueError("item not available in this shop")
    if booking.status not in SWAPPABLE:
        raise InvalidTransition(booking.status, "swap")
    old_code = booking.item.code
    old_status = booking.status
    new_status = BookingStatus.CONFIRMED.value if old_status == BookingStatus.AT_RISK.value else old_status
    try:
        with session.begin_nested():
            booking.item_id = new_item.id
            booking.style_id = new_item.style_id
            booking.status = new_status
            session.flush()
    except IntegrityError as exc:
        if is_exclusion_violation(exc):
            raise ItemConflict([], overridable=False) from exc
        raise
    session.add(
        BookingEvent(
            booking_id=booking.id, from_status=old_status, to_status=new_status,
            actor_id=actor.id, actor_kind=actor.kind.value,
            reason=f"swap {old_code} -> {new_item.code}",
        )
    )
    session.flush()
    session.expire(booking, ["item", "style"])
    return booking


def accept(session: Session, booking: Booking, actor: Actor) -> Booking:
    return transition(session, booking, BookingStatus.CONFIRMED, actor=actor)


def _require_reason(reason: str) -> str:
    reason = reason.strip()
    if not reason:
        raise ValueError("reason required")
    return reason[:300]


def decline(session: Session, booking: Booking, actor: Actor, reason: str) -> Booking:
    return transition(session, booking, BookingStatus.DECLINED, actor=actor, reason=_require_reason(reason))


def cancel_by_shop(session: Session, booking: Booking, actor: Actor, reason: str) -> Booking:
    return transition(
        session, booking, BookingStatus.CANCELLED_BY_SHOP, actor=actor, reason=_require_reason(reason)
    )


def mark_picked_up(session: Session, booking: Booking, actor: Actor) -> Booking:
    return transition(session, booking, BookingStatus.PICKED_UP, actor=actor)


def mark_no_show(session: Session, booking: Booking, actor: Actor) -> Booking:
    return transition(session, booking, BookingStatus.NO_SHOW, actor=actor)


def mark_returned(
    session: Session, booking: Booking, actor: Actor, *, ok: bool, note: str = ""
) -> Booking:
    if not ok:
        note = _require_reason(note)
    transition(session, booking, BookingStatus.COMPLETED, actor=actor, reason=note.strip())
    session.add(
        ItemConditionEvent(
            item_id=booking.item_id,
            booking_id=booking.id,
            kind=(ConditionKind.RETURNED_OK if ok else ConditionKind.RETURNED_ISSUE).value,
            note=note.strip(),
            created_by=actor.id,
        )
    )
    session.flush()
    return booking


def set_item_status(
    session: Session, item: Item, status: str, *, actor: Actor, today: date, note: str = ""
) -> list[Booking]:
    new_status = ItemStatus(status).value
    old_status = item.status
    item.status = new_status
    session.add(
        ItemConditionEvent(
            item_id=item.id, kind=ConditionKind.STATUS_CHANGE.value,
            note=note.strip() or f"{old_status} -> {new_status}", created_by=actor.id,
        )
    )
    session.flush()
    return list(
        session.scalars(
            select(Booking)
            .where(
                Booking.item_id == item.id,
                Booking.status.in_(ACTIVE_STATUSES),
                Booking.return_date >= today,
            )
            .order_by(Booking.pickup_date)
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_staff.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: walk-ins with override, blocks, swaps and lifecycle actions"
```

---

### Task 10: Background jobs, senders and scheduler

**Files:**
- Create: `src/twirl/notify/senders.py`, `src/twirl/jobs.py`, `src/twirl/scheduler.py`
- Modify: `src/twirl/app.py`
- Test: `tests/test_jobs.py`, `tests/test_senders.py`

**Interfaces:**
- Consumes: `Notification`, `render`, `transition`, `SYSTEM`, `notify_admin`, `booking_payload`, `clock`, `Database`, `Settings`.
- Produces: `Sender` protocol (`send(recipient, subject, body) -> str | None`), `LogSender(channel)`, `EmailSender(...)`, `TelegramSender(*, token, admin_chat_id, client=None)`, `build_senders(settings) -> dict[str, Sender]`; `MAX_ATTEMPTS = 5`, `deliver_notifications(session, *, senders, base_url, limit=50) -> int`, `expire_stale_requests(session, *, now, sla_hours) -> int`, `mark_no_shows(session, *, today) -> int`, `mark_not_returned(session, *, today) -> int`; `start_scheduler(db, settings) -> BackgroundScheduler`.

- [ ] **Step 1: Write the failing tests**

`tests/test_senders.py`:

```python
import json

import httpx

from twirl.config import Settings
from twirl.notify.senders import LogSender, TelegramSender, build_senders


def test_telegram_sender_posts_to_admin_chat():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    sender = TelegramSender(
        token="T", admin_chat_id="999", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert sender.send("admin", "", "hello") == "42"
    assert seen["url"] == "https://api.telegram.org/botT/sendMessage"
    assert seen["json"] == {"chat_id": "999", "text": "hello"}


def test_unconfigured_channels_fall_back_to_logging():
    senders = build_senders(Settings(smtp_host="", telegram_bot_token=""))
    assert isinstance(senders["email"], LogSender)
    assert isinstance(senders["telegram"], LogSender)
```

`tests/test_jobs.py`:

```python
from datetime import timedelta

from sqlalchemy import select

from tests.factories import make_booking, make_item, make_shop, make_style
from twirl import clock
from twirl.jobs import (
    MAX_ATTEMPTS, deliver_notifications, expire_stale_requests, mark_no_shows, mark_not_returned,
)
from twirl.models import Notification
from twirl.notify.outbox import notify_admin


class FakeSender:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    def send(self, recipient, subject, body):
        if self.fail:
            raise RuntimeError("boom")
        self.sent.append((recipient, subject, body))
        return "id-1"


def _item(db):
    return make_item(db, make_style(db, make_shop(db)))


PAYLOAD = {"ref": "ABC123", "status": "pending_shop", "shop_name": "Bella", "style_name": "Gown",
           "size": "38", "event_date": "15.05.2027"}


def test_deliver_marks_sent(db):
    notify_admin(db, "new_request_admin", PAYLOAD)
    db.flush()
    telegram = FakeSender()
    assert deliver_notifications(db, senders={"telegram": telegram, "email": FakeSender()}, base_url="https://t") == 1
    row = db.scalars(select(Notification)).one()
    assert (row.status, row.attempts, row.provider_id) == ("sent", 1, "id-1")
    assert "ABC123" in telegram.sent[0][2]


def test_deliver_retries_then_fails(db):
    notify_admin(db, "new_request_admin", PAYLOAD)
    db.flush()
    senders = {"telegram": FakeSender(fail=True), "email": FakeSender()}
    for _ in range(MAX_ATTEMPTS):
        deliver_notifications(db, senders=senders, base_url="")
    row = db.scalars(select(Notification)).one()
    assert (row.status, row.attempts, row.last_error) == ("failed", MAX_ATTEMPTS, "boom")


def test_stale_requests_are_cancelled_and_reported(db):
    now = clock.now()
    item = _item(db)
    pick = clock.today() + timedelta(days=20)
    stale = make_booking(db, item, pickup=pick, return_=pick, kind="online", status="pending_shop",
                         created_at=now - timedelta(hours=25))
    fresh = make_booking(db, item, pickup=pick + timedelta(days=5), return_=pick + timedelta(days=5),
                         kind="online", status="pending_shop", created_at=now - timedelta(hours=2))
    assert expire_stale_requests(db, now=now, sla_hours=24) == 1
    assert (stale.status, fresh.status) == ("cancelled_by_shop", "pending_shop")
    assert db.scalars(select(Notification)).one().template == "request_expired_admin"


def test_no_show_after_one_day_grace_and_blocks_untouched(db):
    today = clock.today()
    late = make_booking(db, _item(db), pickup=today - timedelta(days=2), return_=today - timedelta(days=1))
    grace = make_booking(db, _item(db), pickup=today - timedelta(days=1), return_=today)
    block = make_booking(db, _item(db), pickup=today - timedelta(days=5), return_=today - timedelta(days=4),
                         kind="block")
    assert mark_no_shows(db, today=today) == 1
    assert (late.status, grace.status, block.status) == ("no_show", "confirmed", "confirmed")


def test_not_returned_after_three_days(db):
    today = clock.today()
    item = _item(db)
    overdue = make_booking(db, item, pickup=today - timedelta(days=8), return_=today - timedelta(days=4),
                           status="picked_up")
    recent = make_booking(db, _item(db), pickup=today - timedelta(days=5), return_=today - timedelta(days=2),
                          status="picked_up")
    assert mark_not_returned(db, today=today) == 1
    assert (overdue.status, recent.status) == ("not_returned", "picked_up")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_jobs.py tests/test_senders.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.jobs'`.

- [ ] **Step 3: Implement senders**

`src/twirl/notify/senders.py`:

```python
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from twirl.config import Settings
from twirl.notify.templates import ADMIN_RECIPIENT

log = logging.getLogger(__name__)


class Sender(Protocol):
    def send(self, recipient: str, subject: str, body: str) -> str | None: ...


class LogSender:
    def __init__(self, channel: str) -> None:
        self.channel = channel

    def send(self, recipient: str, subject: str, body: str) -> str | None:
        log.info("[%s -> %s] %s\n%s", self.channel, recipient, subject, body)
        return None


class EmailSender:
    def __init__(self, *, host: str, port: int, user: str, password: str, sender: str) -> None:
        self.host, self.port, self.user, self.password, self.sender = host, port, user, password, sender

    def send(self, recipient: str, subject: str, body: str) -> str | None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)
        return None


class TelegramSender:
    def __init__(self, *, token: str, admin_chat_id: str, client: httpx.Client | None = None) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.admin_chat_id = admin_chat_id
        self.client = client or httpx.Client(timeout=10)

    def send(self, recipient: str, subject: str, body: str) -> str | None:
        chat_id = self.admin_chat_id if recipient == ADMIN_RECIPIENT else recipient
        text = f"{subject}\n\n{body}" if subject else body
        response = self.client.post(self.url, json={"chat_id": chat_id, "text": text})
        response.raise_for_status()
        return str(response.json()["result"]["message_id"])


def build_senders(settings: Settings) -> dict[str, Sender]:
    email: Sender = (
        EmailSender(
            host=settings.smtp_host, port=settings.smtp_port, user=settings.smtp_user,
            password=settings.smtp_password, sender=settings.mail_from,
        )
        if settings.smtp_host
        else LogSender("email")
    )
    telegram: Sender = (
        TelegramSender(token=settings.telegram_bot_token, admin_chat_id=settings.telegram_admin_chat_id)
        if settings.telegram_bot_token and settings.telegram_admin_chat_id
        else LogSender("telegram")
    )
    return {"email": email, "telegram": telegram}
```

- [ ] **Step 4: Implement jobs and the scheduler**

`src/twirl/jobs.py`:

```python
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl import clock
from twirl.booking.actor import SYSTEM
from twirl.booking.timeline import transition
from twirl.models import Booking, BookingKind, BookingStatus, Notification, NotificationStatus
from twirl.notify.outbox import notify_admin
from twirl.notify.payloads import booking_payload
from twirl.notify.senders import Sender
from twirl.notify.templates import render

MAX_ATTEMPTS = 5
NO_SHOW_GRACE_DAYS = 1
NOT_RETURNED_GRACE_DAYS = 3


def deliver_notifications(
    session: Session, *, senders: dict[str, Sender], base_url: str, limit: int = 50
) -> int:
    rows = session.scalars(
        select(Notification)
        .where(Notification.status == NotificationStatus.QUEUED.value)
        .order_by(Notification.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    sent = 0
    for row in rows:
        row.attempts += 1
        try:
            subject, body = render(row.template, row.payload, base_url=base_url)
            row.provider_id = senders[row.channel].send(row.recipient, subject, body)
        except Exception as exc:  # noqa: BLE001 - any delivery failure is recorded and retried
            row.last_error = str(exc)[:1000]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = NotificationStatus.FAILED.value
            continue
        row.status = NotificationStatus.SENT.value
        row.sent_at = clock.now()
        sent += 1
    session.flush()
    return sent


def expire_stale_requests(session: Session, *, now: datetime, sla_hours: int) -> int:
    cutoff = now - timedelta(hours=sla_hours)
    rows = session.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.PENDING_SHOP.value, Booking.created_at < cutoff
        )
    ).all()
    for booking in rows:
        transition(session, booking, BookingStatus.CANCELLED_BY_SHOP, actor=SYSTEM,
                   reason="no reply within SLA")
        notify_admin(session, "request_expired_admin", {**booking_payload(booking), "hours": sla_hours})
    return len(rows)


def mark_no_shows(session: Session, *, today: date) -> int:
    rows = session.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.CONFIRMED.value,
            Booking.kind != BookingKind.BLOCK.value,
            Booking.pickup_date < today - timedelta(days=NO_SHOW_GRACE_DAYS),
        )
    ).all()
    for booking in rows:
        transition(session, booking, BookingStatus.NO_SHOW, actor=SYSTEM, reason="pickup date passed")
    return len(rows)


def mark_not_returned(session: Session, *, today: date) -> int:
    rows = session.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.PICKED_UP.value,
            Booking.return_date < today - timedelta(days=NOT_RETURNED_GRACE_DAYS),
        )
    ).all()
    for booking in rows:
        transition(session, booking, BookingStatus.NOT_RETURNED, actor=SYSTEM, reason="return overdue")
    return len(rows)
```

`src/twirl/scheduler.py`:

```python
import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from twirl import clock
from twirl.config import Settings
from twirl.db import Database
from twirl.jobs import deliver_notifications, expire_stale_requests, mark_no_shows, mark_not_returned
from twirl.notify.senders import build_senders

log = logging.getLogger(__name__)


def _run(db: Database, name: str, fn: Callable[..., int], kwargs: Callable[[], dict]) -> None:
    with db.sessionmaker() as session:
        try:
            count = fn(session, **kwargs())
            session.commit()
            if count:
                log.info("job %s processed %d row(s)", name, count)
        except Exception:
            session.rollback()
            log.exception("job %s failed", name)


def start_scheduler(db: Database, settings: Settings) -> BackgroundScheduler:
    """Run in exactly one process. With several web workers, enable it on one only."""
    senders = build_senders(settings)
    scheduler = BackgroundScheduler(timezone=clock.TZ)
    jobs = [
        ("deliver", deliver_notifications,
         lambda: {"senders": senders, "base_url": settings.base_url}, {"seconds": 30}),
        ("expire_requests", expire_stale_requests,
         lambda: {"now": clock.now(), "sla_hours": settings.request_sla_hours}, {"minutes": 5}),
        ("no_shows", mark_no_shows, lambda: {"today": clock.today()}, {"hours": 1}),
        ("not_returned", mark_not_returned, lambda: {"today": clock.today()}, {"hours": 1}),
    ]
    for name, fn, kwargs, interval in jobs:
        scheduler.add_job(
            _run, "interval", args=[db, name, fn, kwargs], id=name, max_instances=1,
            coalesce=True, **interval,
        )
    scheduler.start()
    return scheduler
```

Replace `src/twirl/app.py` with:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from twirl.config import Settings, get_settings
from twirl.db import Database
from twirl.scheduler import start_scheduler
from twirl.web import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if app.state.settings.run_scheduler:
        scheduler = start_scheduler(app.state.db, app.state.settings)
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    app.state.db.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Twirl", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.include_router(health.router)
    return app
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: notification delivery, SLA expiry, no-show and overdue jobs"
```

---

### Task 11: Templating, translations, sessions and CSRF

**Files:**
- Create: `babel.cfg`, `src/twirl/i18n.py`, `src/twirl/auth/__init__.py`, `src/twirl/auth/csrf.py`, `src/twirl/web/templating.py`, `src/twirl/web/forms.py`, `src/twirl/web/pages.py`
- Create: `src/twirl/templates/base.html`, `src/twirl/templates/home.html`, `src/twirl/static/app.css`, `src/twirl/static/htmx.min.js` (downloaded)
- Create: `src/twirl/locale/sq/LC_MESSAGES/messages.po` (+ compiled `.mo`)
- Modify: `src/twirl/app.py`
- Test: `tests/helpers.py`, `tests/test_web_basics.py`

**Interfaces:**
- Produces: `SUPPORTED_LOCALES`, `DEFAULT_LOCALE`, `LOCALE_COOKIE`, `get_translations(locale)`, `pick_locale(request) -> str`, `N_(s) -> s`; `get_csrf_token(request) -> str`, `verify_csrf(request)` (async dependency, 403 on failure), `CSRF_FIELD = "csrf_token"`; `render(request, name, context=None, *, status_code=200) -> HTMLResponse` (adds `locale` to context), filters `money(cents, locale)` and `date`; `form_data(request) -> FormData` (async dependency), `validate_form(model_cls, form, list_fields=()) -> tuple[model | None, dict[str, str]]`; test helpers `csrf_from(client, path="/")`, `post(client, path, data=None, files=None)`.

- [ ] **Step 1: Write the failing tests**

`tests/helpers.py`:

```python
import re

CSRF_RE = re.compile(r'name="csrf-token" content="([^"]+)"')


def csrf_from(client, path: str = "/") -> str:
    match = CSRF_RE.search(client.get(path).text)
    assert match, f"no csrf meta tag on {path}"
    return match.group(1)


def post(client, path: str, data: dict | None = None, files=None):
    token = csrf_from(client, "/")
    return client.post(
        path, data={**(data or {}), "csrf_token": token}, files=files, follow_redirects=False
    )
```

`tests/test_web_basics.py`:

```python
from datetime import date

import pytest

from tests.helpers import csrf_from
from twirl.web.templating import format_date, format_money


def test_home_defaults_to_albanian(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'lang="sq"' in response.text
    assert "Merr fustanin me qira" in response.text


def test_home_in_english_with_cookie(client):
    client.cookies.set("lang", "en")
    response = client.get("/")
    assert 'lang="en"' in response.text
    assert "Rent the dress" in response.text


def test_language_switch_sets_cookie_and_redirects(client):
    response = client.get("/lang/en?next=/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "lang=en" in response.headers["set-cookie"]


def test_language_switch_refuses_external_redirect(client):
    response = client.get("/lang/en?next=//evil.example", follow_redirects=False)
    assert response.headers["location"] == "/"


def test_pages_carry_a_csrf_token(client):
    assert len(csrf_from(client, "/")) > 20


@pytest.mark.parametrize(
    "cents, locale, expected",
    [(5500, "sq", "55 €"), (5500, "en", "€55"), (5550, "sq", "55,50 €"), (5550, "en", "€55.50")],
)
def test_format_money(cents, locale, expected):
    assert format_money(cents, locale) == expected


def test_format_date():
    assert format_date(date(2027, 5, 15)) == "15.05.2027"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_basics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.web.templating'`.

- [ ] **Step 3: Implement i18n, CSRF, templating and forms**

`babel.cfg`:

```
[python: src/**.py]

[jinja2: src/twirl/templates/**.html]
extensions = jinja2.ext.i18n
```

`src/twirl/i18n.py`:

```python
from functools import lru_cache
from pathlib import Path

from babel.support import NullTranslations, Translations
from starlette.requests import Request

LOCALE_DIR = Path(__file__).parent / "locale"
SUPPORTED_LOCALES = ("sq", "en")
DEFAULT_LOCALE = "sq"
LOCALE_COOKIE = "lang"


def N_(message: str) -> str:
    """Mark a string for extraction; it is translated later where it is rendered."""
    return message


@lru_cache
def get_translations(locale: str) -> NullTranslations:
    if locale == "en":
        return NullTranslations()
    return Translations.load(str(LOCALE_DIR), [locale])


def pick_locale(request: Request) -> str:
    value = request.cookies.get(LOCALE_COOKIE)
    return value if value in SUPPORTED_LOCALES else DEFAULT_LOCALE
```

`src/twirl/auth/__init__.py`: empty file.

`src/twirl/auth/csrf.py`:

```python
import secrets

from fastapi import HTTPException
from starlette.requests import Request

CSRF_SESSION_KEY = "csrf"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"


def get_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def verify_csrf(request: Request) -> None:
    expected = request.session.get(CSRF_SESSION_KEY)
    sent = request.headers.get(CSRF_HEADER)
    if not sent:
        form = await request.form()
        sent = form.get(CSRF_FIELD)
    if not expected or not isinstance(sent, str) or not secrets.compare_digest(expected, sent):
        raise HTTPException(status_code=403, detail="CSRF check failed")
```

`src/twirl/web/templating.py`:

```python
from contextvars import ContextVar
from datetime import date

from babel.support import NullTranslations
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse

from twirl.auth.csrf import get_csrf_token
from twirl.i18n import get_translations, pick_locale

_current: ContextVar[NullTranslations] = ContextVar("twirl_translations", default=NullTranslations())


def _gettext(message: str) -> str:
    return _current.get().gettext(message)


def _ngettext(singular: str, plural: str, n: int) -> str:
    return _current.get().ngettext(singular, plural, n)


def format_money(cents: int, locale: str) -> str:
    if cents % 100 == 0:
        number = str(cents // 100)
    else:
        number = f"{cents / 100:.2f}"
        if locale == "sq":
            number = number.replace(".", ",")
    return f"{number} €" if locale == "sq" else f"€{number}"


def format_date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _build_env() -> Environment:
    env = Environment(
        loader=PackageLoader("twirl", "templates"),
        autoescape=select_autoescape(["html"]),
        extensions=["jinja2.ext.i18n"],
    )
    env.install_gettext_callables(_gettext, _ngettext, newstyle=True)
    env.filters["money"] = format_money
    env.filters["date"] = format_date
    env.globals["csrf_token"] = get_csrf_token
    return env


templates = Jinja2Templates(env=_build_env())


def render(
    request: Request, name: str, context: dict | None = None, *, status_code: int = 200
) -> HTMLResponse:
    locale = pick_locale(request)
    token = _current.set(get_translations(locale))
    try:
        return templates.TemplateResponse(
            request, name, {"locale": locale, **(context or {})}, status_code=status_code
        )
    finally:
        _current.reset(token)
```

`src/twirl/web/forms.py`:

```python
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from starlette.datastructures import FormData
from starlette.requests import Request

M = TypeVar("M", bound=BaseModel)


async def form_data(request: Request) -> FormData:
    return await request.form()


def validate_form(
    model_cls: type[M], form: FormData, list_fields: tuple[str, ...] = ()
) -> tuple[M | None, dict[str, str]]:
    data: dict = {key: form.get(key) for key in form.keys() if key not in list_fields}
    for key in list_fields:
        data[key] = form.getlist(key)
    data.pop("csrf_token", None)
    try:
        return model_cls.model_validate(data), {}
    except ValidationError as exc:
        return None, {str(err["loc"][0]) if err["loc"] else "__all__": err["msg"] for err in exc.errors()}
```

`src/twirl/web/pages.py`:

```python
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from twirl.i18n import LOCALE_COOKIE, SUPPORTED_LOCALES
from twirl.web.templating import render

router = APIRouter()


def safe_next(target: str | None, default: str = "/") -> str:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return default


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return render(request, "home.html")


@router.get("/lang/{code}")
def set_language(code: str, next_: str = Query("/", alias="next")):
    response = RedirectResponse(safe_next(next_), status_code=303)
    if code in SUPPORTED_LOCALES:
        response.set_cookie(LOCALE_COOKIE, code, max_age=365 * 24 * 3600, samesite="lax")
    return response
```

- [ ] **Step 4: Add templates, static files and the Albanian catalog**

```bash
mkdir -p src/twirl/templates src/twirl/static src/twirl/locale/sq/LC_MESSAGES
curl -sSL -o src/twirl/static/htmx.min.js https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
```

`src/twirl/templates/base.html`:

```html
<!doctype html>
<html lang="{{ locale }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="csrf-token" content="{{ csrf_token(request) }}">
  <title>{% block title %}Twirl{% endblock %}</title>
  {% block head %}{% endblock %}
  <link rel="stylesheet" href="{{ url_for('static', path='app.css') }}">
  <script src="{{ url_for('static', path='htmx.min.js') }}" defer></script>
</head>
<body hx-headers='{"X-CSRF-Token": "{{ csrf_token(request) }}"}'>
  <header class="topbar">
    <a href="/" class="brand">Twirl</a>
    <nav>{% block nav %}{% endblock %}</nav>
    <span class="lang">
      <a href="/lang/sq?next={{ request.url.path }}">SQ</a> ·
      <a href="/lang/en?next={{ request.url.path }}">EN</a>
    </span>
  </header>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

`src/twirl/templates/home.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>{{ _("Rent the dress. Skip the price tag.") }}</h1>
<p>{{ _("Dress rental shops in Kosovo, bookable online.") }}</p>
{% endblock %}
```

`src/twirl/static/app.css` (functional minimum; visual design is a later plan):

```css
:root { font-family: system-ui, sans-serif; line-height: 1.4; }
body { margin: 0; }
main { max-width: 960px; margin: 0 auto; padding: 1rem; }
.topbar { display: flex; gap: 1rem; align-items: center; padding: .5rem 1rem; border-bottom: 1px solid #ddd; flex-wrap: wrap; }
.topbar nav { display: flex; gap: .75rem; flex: 1; flex-wrap: wrap; }
.brand { font-weight: 700; text-decoration: none; }
label { display: block; margin: .5rem 0; }
input, select, textarea, button { font: inherit; min-height: 44px; }
button { padding: 0 1rem; }
.inline { display: inline; }
.error { color: #a00; font-weight: 600; }
.muted { color: #666; }
.hp { position: absolute; left: -10000px; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ddd; padding: .25rem .5rem; text-align: left; }
.calendar td[data-kind] { background: #e8f0ff; }
.calendar td[data-kind="block"] { background: #eee; }
.calendar td[data-status="pending_shop"] { background: #fff4d6; }
.sizes .taken { color: #999; text-decoration: line-through; }
.actions form { display: inline-block; margin: .25rem; }
```

`src/twirl/locale/sq/LC_MESSAGES/messages.po`:

```
msgid ""
msgstr ""
"Project-Id-Version: twirl\n"
"Language: sq\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

msgid "Rent the dress. Skip the price tag."
msgstr "Merr fustanin me qira, pa e blerë."

msgid "Dress rental shops in Kosovo, bookable online."
msgstr "Dyqanet e fustaneve me qira në Kosovë, me rezervim online."
```

```bash
uv run pybabel compile -d src/twirl/locale -D messages
```

Replace `src/twirl/app.py` with:

```python
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from twirl.config import Settings, get_settings
from twirl.db import Database
from twirl.scheduler import start_scheduler
from twirl.web import health, pages

STATIC_DIR = Path(__file__).parent / "static"
SESSION_MAX_AGE = 30 * 24 * 3600


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if app.state.settings.run_scheduler:
        scheduler = start_scheduler(app.state.db, app.state.settings)
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    app.state.db.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Twirl", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="twirl_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=settings.https_only,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(health.router)
    app.include_router(pages.router)
    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web_basics.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: Jinja2 templating with Albanian default, sessions and CSRF"
```

---

### Task 12: Shop login

**Files:**
- Create: `src/twirl/auth/passwords.py`, `src/twirl/auth/deps.py`, `src/twirl/ratelimit.py`, `src/twirl/web/auth.py`, `src/twirl/web/shop_home.py`
- Create: `src/twirl/templates/auth/login.html`, `src/twirl/templates/shop/base.html`, `src/twirl/templates/shop/today.html`
- Modify: `src/twirl/app.py`, `tests/conftest.py`, `tests/helpers.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `render`, `verify_csrf`, `safe_next`, `get_db`, `User`, `Shop`, `ShopUser`, `Actor`.
- Produces: `hash_password(p) -> str`, `verify_password(hash_, p) -> bool`; `SESSION_USER_KEY = "uid"`, `LoginRequired(next_path)`, `ShopContext(user, shop, role)` with `.is_owner` and `.actor`, dependencies `current_user`, `require_shop`, `require_owner`, functions `login_user(request, user)`, `logout_user(request)`; `RateLimiter(max_events, window_seconds, clock=time.monotonic).allow(key) -> bool`, `client_ip(request, *, trust_cf) -> str`; fixtures `PASSWORD`, `shop`, `owner`, `owner_client`, `staff_client`; helper `login(client, email, password=PASSWORD)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/helpers.py`:

```python
PASSWORD = "pw-123456"


def login(client, email: str, password: str = PASSWORD):
    token = csrf_from(client, "/login")
    response = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token, "next": "/shop"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response
```

Append to `tests/conftest.py`:

```python
from tests.factories import make_shop, make_shop_user  # noqa: E402
from tests.helpers import PASSWORD, login  # noqa: E402
from twirl.auth.passwords import hash_password  # noqa: E402

_PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture
def shop(db):
    return make_shop(db, name="Bella", slug="bella")


@pytest.fixture
def owner(db, shop):
    return make_shop_user(db, shop, role="owner", password_hash=_PASSWORD_HASH)


@pytest.fixture
def owner_client(client, owner):
    login(client, owner.email)
    return client


@pytest.fixture
def staff_client(app, db, shop):
    staff = make_shop_user(db, shop, role="staff", password_hash=_PASSWORD_HASH)
    with TestClient(app) as c:
        login(c, staff.email)
        yield c
```

`tests/test_auth.py`:

```python
from datetime import UTC, datetime

from tests.factories import make_user
from tests.helpers import PASSWORD, csrf_from, login
from twirl.auth.passwords import hash_password
from twirl.ratelimit import RateLimiter


def _login_post(client, email, password):
    token = csrf_from(client, "/login")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_shop_page_requires_login(client):
    response = client.get("/shop", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/shop"


def test_owner_logs_in_and_sees_shop(client, owner):
    login(client, owner.email)
    response = client.get("/shop")
    assert response.status_code == 200
    assert "Bella" in response.text


def test_wrong_password_is_rejected(client, owner):
    assert _login_post(client, owner.email, "nope").status_code == 400


def test_login_without_csrf_is_forbidden(client, owner):
    response = client.post("/login", data={"email": owner.email, "password": PASSWORD})
    assert response.status_code == 403


def test_blocked_user_cannot_log_in(client, db, owner):
    owner.blocked_at = datetime.now(UTC)
    db.flush()
    assert _login_post(client, owner.email, PASSWORD).status_code == 400


def test_user_without_shop_gets_403(client, db):
    user = make_user(db, kind="shop", password_hash=hash_password(PASSWORD))
    login(client, user.email)
    assert client.get("/shop").status_code == 403


def test_logout_ends_session(owner_client):
    token = csrf_from(owner_client, "/shop")
    owner_client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert owner_client.get("/shop", follow_redirects=False).status_code == 303


def test_login_is_rate_limited(client, owner):
    statuses = [_login_post(client, owner.email, "nope").status_code for _ in range(11)]
    assert statuses[-1] == 429


def test_rate_limiter_window():
    now = [0.0]
    limiter = RateLimiter(2, 60, clock=lambda: now[0])
    assert limiter.allow("k") and limiter.allow("k")
    assert not limiter.allow("k")
    now[0] = 61
    assert limiter.allow("k")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.auth.passwords'`.

- [ ] **Step 3: Implement passwords, rate limiter and auth dependencies**

`src/twirl/auth/passwords.py`:

```python
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False
```

`src/twirl/ratelimit.py`:

```python
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from starlette.requests import Request


class RateLimiter:
    """In-process sliding window. Correct for a single web process, which is the deployment target."""

    def __init__(self, max_events: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.max_events = max_events
        self.window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - self.window:
                events.popleft()
            if len(events) >= self.max_events:
                return False
            events.append(now)
            return True


def client_ip(request: Request, *, trust_cf: bool) -> str:
    if trust_cf and (ip := request.headers.get("cf-connecting-ip")):
        return ip
    return request.client.host if request.client else "unknown"
```

`src/twirl/auth/deps.py`:

```python
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl.booking.actor import Actor
from twirl.db import get_db
from twirl.models import ActorKind, Shop, ShopRole, ShopUser, User

SESSION_USER_KEY = "uid"


class LoginRequired(Exception):
    def __init__(self, next_path: str) -> None:
        super().__init__(next_path)
        self.next_path = next_path


@dataclass(frozen=True)
class ShopContext:
    user: User
    shop: Shop
    role: str

    @property
    def is_owner(self) -> bool:
        return self.role == ShopRole.OWNER.value

    @property
    def actor(self) -> Actor:
        return Actor(ActorKind.SHOP, self.user.id)


def login_user(request: Request, user: User) -> None:
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id


def logout_user(request: Request) -> None:
    request.session.clear()


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or user.blocked_at is not None:
        return None
    return user


def require_shop(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
) -> ShopContext:
    if user is None:
        raise LoginRequired(request.url.path)
    link = db.scalar(select(ShopUser).where(ShopUser.user_id == user.id))
    if link is None:
        raise HTTPException(status_code=403)
    return ShopContext(user=user, shop=db.get(Shop, link.shop_id), role=link.role)


def require_owner(ctx: ShopContext = Depends(require_shop)) -> ShopContext:
    if not ctx.is_owner:
        raise HTTPException(status_code=403)
    return ctx
```

- [ ] **Step 4: Implement login routes, the placeholder Today page and templates**

`src/twirl/web/auth.py`:

```python
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import login_user, logout_user
from twirl.auth.passwords import verify_password
from twirl.db import get_db
from twirl.i18n import N_
from twirl.models import User
from twirl.ratelimit import client_ip
from twirl.web.pages import safe_next
from twirl.web.templating import render

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next_: str = Query("/shop", alias="next")):
    return render(request, "auth/login.html", {"next": safe_next(next_, "/shop"), "error": None})


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_: str = Form("/shop", alias="next"),
    db: Session = Depends(get_db),
):
    target = safe_next(next_, "/shop")
    settings = request.app.state.settings
    if not request.app.state.login_limiter.allow(client_ip(request, trust_cf=settings.trust_cf_connecting_ip)):
        return render(
            request, "auth/login.html",
            {"next": target, "error": N_("Too many attempts. Try again in a few minutes.")},
            status_code=429,
        )
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if (
        user is None
        or user.password_hash is None
        or user.blocked_at is not None
        or not verify_password(user.password_hash, password)
    ):
        return render(
            request, "auth/login.html",
            {"next": target, "error": N_("Wrong email or password.")}, status_code=400,
        )
    login_user(request, user)
    return RedirectResponse(target, status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)
```

`src/twirl/web/shop_home.py` (placeholder, replaced in Task 16):

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from twirl.auth.deps import ShopContext, require_shop
from twirl.web.templating import render

router = APIRouter()


@router.get("/shop", response_class=HTMLResponse)
def today(request: Request, ctx: ShopContext = Depends(require_shop)):
    return render(request, "shop/today.html", {"ctx": ctx})
```

`src/twirl/templates/auth/login.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>{{ _("Shop login") }}</h1>
{% if error %}<p class="error" role="alert">{{ _(error) }}</p>{% endif %}
<form method="post" action="/login">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  <input type="hidden" name="next" value="{{ next }}">
  <label>{{ _("Email") }} <input type="email" name="email" required autocomplete="username"></label>
  <label>{{ _("Password") }} <input type="password" name="password" required autocomplete="current-password"></label>
  <button>{{ _("Log in") }}</button>
</form>
{% endblock %}
```

`src/twirl/templates/shop/base.html`:

```html
{% extends "base.html" %}
{% block nav %}
<a href="/shop">{{ _("Today") }}</a>
<a href="/shop/calendar">{{ _("Calendar") }}</a>
<a href="/shop/walk-in">{{ _("Walk-in") }}</a>
<a href="/shop/styles">{{ _("Dresses") }}</a>
{% if ctx.is_owner %}<a href="/shop/settings">{{ _("Settings") }}</a>{% endif %}
<form method="post" action="/logout" class="inline">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  <button>{{ _("Log out") }}</button>
</form>
{% endblock %}
```

`src/twirl/templates/shop/today.html`:

```html
{% extends "shop/base.html" %}
{% block content %}
<h1>{{ ctx.shop.name }}</h1>
{% endblock %}
```

Replace `src/twirl/app.py` with:

```python
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from twirl.auth.deps import LoginRequired
from twirl.config import Settings, get_settings
from twirl.db import Database
from twirl.ratelimit import RateLimiter
from twirl.scheduler import start_scheduler
from twirl.web import auth, health, pages, shop_home

STATIC_DIR = Path(__file__).parent / "static"
SESSION_MAX_AGE = 30 * 24 * 3600


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if app.state.settings.run_scheduler:
        scheduler = start_scheduler(app.state.db, app.state.settings)
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    app.state.db.engine.dispose()


async def _login_redirect(request: Request, exc: LoginRequired) -> RedirectResponse:
    return RedirectResponse(f"/login?next={quote(exc.next_path)}", status_code=303)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Twirl", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.login_limiter = RateLimiter(10, 15 * 60)
    app.state.request_limiter = RateLimiter(settings.request_rate_limit_per_hour, 3600)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="twirl_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=settings.https_only,
    )
    app.add_exception_handler(LoginRequired, _login_redirect)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    for router in (health.router, pages.router, auth.router, shop_home.router):
        app.include_router(router)
    return app
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: shop login with argon2, session auth and rate limiting"
```

---

### Task 13: Shop settings — profile, rules, closed days, closures

**Files:**
- Create: `src/twirl/web/shop_settings.py`, `src/twirl/templates/shop/settings.html`
- Modify: `src/twirl/app.py`
- Test: `tests/test_shop_settings.py`

**Interfaces:**
- Consumes: `require_owner`, `verify_csrf`, `form_data`, `validate_form`, `render`, `normalize_phone`, `ShopHours`, `ShopClosure`, `N_`.
- Produces: routes `GET/POST /shop/settings`, `POST /shop/settings/closures`, `POST /shop/settings/closures/{closure_id}/delete`.

- [ ] **Step 1: Write the failing tests**

`tests/test_shop_settings.py`:

```python
from datetime import date

from tests.factories import make_shop
from tests.helpers import post
from twirl.models import ShopClosure


def _data(**over):
    data = {
        "name": "Bella Dresses", "city": "Ferizaj", "address": "Rr. Dëshmorët 1",
        "phone": "044 111 222", "whatsapp": "044 111 222", "viber": "", "instagram": "bella.ks",
        "terms_text": "Depozitë 50 €", "pickup_lead_days": "2", "return_after_days": "1",
        "prep_days": "0", "cleaning_days": "2", "max_rental_days": "7",
    }
    data.update(over)
    return data


def test_owner_sees_settings(owner_client):
    response = owner_client.get("/shop/settings")
    assert response.status_code == 200
    assert 'name="cleaning_days"' in response.text


def test_staff_cannot_open_settings(staff_client):
    assert staff_client.get("/shop/settings").status_code == 403


def test_owner_saves_settings_and_closed_days(owner_client, shop):
    response = post(owner_client, "/shop/settings", {**_data(), "closed_weekdays": ["6"]})
    assert response.status_code == 303
    assert (shop.name, shop.cleaning_days, shop.whatsapp, shop.viber) == (
        "Bella Dresses", 2, "+38344111222", None,
    )
    assert [h.weekday for h in shop.hours if h.closed] == [6]


def test_invalid_settings_are_not_saved(owner_client, shop):
    response = post(owner_client, "/shop/settings", _data(cleaning_days="9"))
    assert response.status_code == 400
    assert shop.cleaning_days == 1


def test_invalid_phone_is_reported(owner_client, shop):
    response = post(owner_client, "/shop/settings", _data(phone="123"))
    assert response.status_code == 400


def test_add_and_delete_closure(owner_client, db, shop):
    response = post(owner_client, "/shop/settings/closures",
                    {"starts_on": "2027-08-01", "ends_on": "2027-08-10", "reason": "Pushime"})
    assert response.status_code == 303
    closure = db.query(ShopClosure).filter_by(shop_id=shop.id).one()
    assert (closure.starts_on, closure.ends_on) == (date(2027, 8, 1), date(2027, 8, 10))
    assert post(owner_client, f"/shop/settings/closures/{closure.id}/delete").status_code == 303
    assert db.query(ShopClosure).filter_by(shop_id=shop.id).count() == 0


def test_cannot_delete_another_shops_closure(owner_client, db):
    other = make_shop(db)
    closure = ShopClosure(shop_id=other.id, starts_on=date(2027, 1, 1), ends_on=date(2027, 1, 2))
    db.add(closure)
    db.flush()
    assert post(owner_client, f"/shop/settings/closures/{closure.id}/delete").status_code == 404


def test_closure_end_before_start_is_rejected(owner_client):
    response = post(owner_client, "/shop/settings/closures",
                    {"starts_on": "2027-08-10", "ends_on": "2027-08-01", "reason": ""})
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_shop_settings.py -v`
Expected: FAIL with 404 on `/shop/settings`.

- [ ] **Step 3: Implement the settings routes**

`src/twirl/web/shop_settings.py`:

```python
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import ShopContext, require_owner
from twirl.db import get_db
from twirl.i18n import N_
from twirl.models import ShopClosure, ShopHours
from twirl.phones import normalize_phone
from twirl.web.forms import form_data, validate_form
from twirl.web.templating import render

router = APIRouter(prefix="/shop/settings")

WEEKDAY_NAMES = [
    N_("Monday"), N_("Tuesday"), N_("Wednesday"), N_("Thursday"), N_("Friday"), N_("Saturday"),
    N_("Sunday"),
]
FIELDS = (
    "name", "city", "address", "phone", "whatsapp", "viber", "instagram", "terms_text",
    "pickup_lead_days", "return_after_days", "prep_days", "cleaning_days", "max_rental_days",
)
OPTIONAL_TEXT = ("phone", "whatsapp", "viber", "instagram")


class SettingsForm(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=60)
    address: str = Field(default="", max_length=255)
    phone: str = ""
    whatsapp: str = ""
    viber: str = ""
    instagram: str = Field(default="", max_length=60)
    terms_text: str = Field(default="", max_length=4000)
    pickup_lead_days: int = Field(ge=0, le=5)
    return_after_days: int = Field(ge=0, le=3)
    prep_days: int = Field(ge=0, le=2)
    cleaning_days: int = Field(ge=0, le=5)
    max_rental_days: int = Field(ge=1, le=14)
    closed_weekdays: list[int] = []

    @field_validator("phone", "whatsapp", "viber")
    @classmethod
    def _phone(cls, value: str) -> str:
        value = value.strip()
        return normalize_phone(value) if value else ""

    @field_validator("closed_weekdays")
    @classmethod
    def _weekdays(cls, value: list[int]) -> list[int]:
        if any(not 0 <= day <= 6 for day in value):
            raise ValueError("weekday out of range")
        return sorted(set(value))


class ClosureForm(BaseModel):
    starts_on: date
    ends_on: date
    reason: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _order(self) -> "ClosureForm":
        if self.ends_on < self.starts_on:
            raise ValueError("end before start")
        return self


def _values_from_shop(ctx: ShopContext) -> dict:
    values = {f: ("" if getattr(ctx.shop, f) is None else getattr(ctx.shop, f)) for f in FIELDS}
    values["closed_weekdays"] = [h.weekday for h in ctx.shop.hours if h.closed]
    return values


def _values_from_form(form: FormData) -> dict:
    values = {f: form.get(f, "") for f in FIELDS}
    values["closed_weekdays"] = [int(v) for v in form.getlist("closed_weekdays") if str(v).isdigit()]
    return values


def _page(request: Request, ctx: ShopContext, *, values: dict, errors: dict | None = None,
          status_code: int = 200, saved: bool = False):
    return render(
        request, "shop/settings.html",
        {
            "ctx": ctx, "values": values, "errors": errors or {}, "saved": saved,
            "weekdays": list(enumerate(WEEKDAY_NAMES)), "closures": ctx.shop.closures,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, saved: bool = False, ctx: ShopContext = Depends(require_owner)):
    return _page(request, ctx, values=_values_from_shop(ctx), saved=saved)


@router.post("", dependencies=[Depends(verify_csrf)])
def save_settings(
    request: Request,
    form: FormData = Depends(form_data),
    ctx: ShopContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    parsed, errors = validate_form(SettingsForm, form, list_fields=("closed_weekdays",))
    if parsed is None:
        return _page(request, ctx, values=_values_from_form(form), errors=errors, status_code=400)
    shop = ctx.shop
    for field in FIELDS:
        value = getattr(parsed, field)
        setattr(shop, field, (value or None) if field in OPTIONAL_TEXT else value)
    existing = {h.weekday: h for h in shop.hours}
    for weekday in range(7):
        hours = existing.get(weekday)
        if hours is None:
            hours = ShopHours(weekday=weekday)
            shop.hours.append(hours)
        hours.closed = weekday in parsed.closed_weekdays
    db.commit()
    return RedirectResponse("/shop/settings?saved=true", status_code=303)


@router.post("/closures", dependencies=[Depends(verify_csrf)])
def add_closure(
    request: Request,
    form: FormData = Depends(form_data),
    ctx: ShopContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    parsed, errors = validate_form(ClosureForm, form)
    if parsed is None:
        return _page(request, ctx, values=_values_from_shop(ctx), errors=errors, status_code=400)
    ctx.shop.closures.append(
        ShopClosure(starts_on=parsed.starts_on, ends_on=parsed.ends_on, reason=parsed.reason.strip())
    )
    db.commit()
    return RedirectResponse("/shop/settings", status_code=303)


@router.post("/closures/{closure_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_closure(
    closure_id: int, ctx: ShopContext = Depends(require_owner), db: Session = Depends(get_db)
):
    closure = db.get(ShopClosure, closure_id)
    if closure is None or closure.shop_id != ctx.shop.id:
        raise HTTPException(status_code=404)
    ctx.shop.closures.remove(closure)
    db.commit()
    return RedirectResponse("/shop/settings", status_code=303)
```

`src/twirl/templates/shop/settings.html`:

```html
{% extends "shop/base.html" %}
{% block content %}
{% macro field(name, label, type="text") %}
<label>{{ _(label) }}
  <input type="{{ type }}" name="{{ name }}" value="{{ values[name] }}">
  {% if errors[name] %}<span class="error">{{ errors[name] }}</span>{% endif %}
</label>
{% endmacro %}
<h1>{{ _("Shop settings") }}</h1>
{% if saved %}<p role="status">{{ _("Saved.") }}</p>{% endif %}
<form method="post" action="/shop/settings">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  {{ field("name", "Shop name") }}
  {{ field("city", "City") }}
  {{ field("address", "Address") }}
  {{ field("phone", "Phone", "tel") }}
  {{ field("whatsapp", "WhatsApp number", "tel") }}
  {{ field("viber", "Viber number", "tel") }}
  {{ field("instagram", "Instagram handle") }}
  <label>{{ _("Your terms (deposit, ID, late fee, damage)") }}
    <textarea name="terms_text" rows="4">{{ values.terms_text }}</textarea></label>
  <fieldset><legend>{{ _("Rental rules") }}</legend>
    {{ field("pickup_lead_days", "Pickup: days before the event", "number") }}
    {{ field("return_after_days", "Return: days after the event", "number") }}
    {{ field("prep_days", "Preparation days before pickup", "number") }}
    {{ field("cleaning_days", "Cleaning days after return", "number") }}
    {{ field("max_rental_days", "Longest rental in days", "number") }}
  </fieldset>
  <fieldset><legend>{{ _("Closed every week on") }}</legend>
    {% for number, day in weekdays %}
    <label class="inline"><input type="checkbox" name="closed_weekdays" value="{{ number }}"
      {% if number in values.closed_weekdays %}checked{% endif %}> {{ _(day) }}</label>
    {% endfor %}
  </fieldset>
  <button>{{ _("Save") }}</button>
</form>

<h2>{{ _("Closures") }}</h2>
{% if errors.get('ends_on') or errors.get('__all__') %}<p class="error">{{ _("The end date must be on or after the start date.") }}</p>{% endif %}
<ul>
{% for closure in closures %}
  <li>{{ closure.starts_on|date }} – {{ closure.ends_on|date }} {{ closure.reason }}
    <form method="post" action="/shop/settings/closures/{{ closure.id }}/delete" class="inline">
      <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
      <button>{{ _("Remove") }}</button></form></li>
{% endfor %}
</ul>
<form method="post" action="/shop/settings/closures">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  <label>{{ _("From") }} <input type="date" name="starts_on" required></label>
  <label>{{ _("To") }} <input type="date" name="ends_on" required></label>
  <label>{{ _("Reason") }} <input name="reason" maxlength="200"></label>
  <button>{{ _("Add closure") }}</button>
</form>
{% endblock %}
```

In `src/twirl/app.py`, change the web import to `from twirl.web import auth, health, pages, shop_home, shop_settings` and the router tuple to `(health.router, pages.router, auth.router, shop_home.router, shop_settings.router)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_shop_settings.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: shop settings with rental rules, closed days and closures"
```

---

### Task 14: Image pipeline and storage

**Files:**
- Create: `src/twirl/images.py`, `src/twirl/storage.py`
- Modify: `src/twirl/catalog.py`, `src/twirl/app.py`
- Test: `tests/test_images.py`

**Interfaces:**
- Consumes: `Style`, `StyleImage`.
- Produces: `MAX_UPLOAD_BYTES`, `InvalidImage(code)`, `ProcessedImage(variants: dict[str, bytes], width, height)`, `process_image(data) -> ProcessedImage`; `Storage` protocol, `LocalStorage(root, base_url="/media")` with `put(key, data, content_type)`, `url(key)`, `delete(key)`; `get_storage(request) -> Storage`; in `catalog.py`: `MAX_IMAGES_PER_STYLE = 8`, `save_style_image(session, storage, style, data) -> StyleImage`, `image_url(storage, image, variant="thumb") -> str`; `app.state.storage` and the `/media` mount.

- [ ] **Step 1: Write the failing tests**

Append to `tests/helpers.py`:

```python
import io  # noqa: E402

from PIL import Image  # noqa: E402


def png_bytes(width: int = 600, height: int = 800) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 60)).save(buffer, "PNG")
    return buffer.getvalue()
```

`tests/test_images.py`:

```python
import io

import pytest
from PIL import Image

from tests.factories import make_shop, make_style
from tests.helpers import png_bytes
from twirl.catalog import MAX_IMAGES_PER_STYLE, image_url, save_style_image
from twirl.images import MAX_UPLOAD_BYTES, InvalidImage, process_image
from twirl.storage import LocalStorage


def _jpeg_with_exif() -> bytes:
    image = Image.new("RGB", (1600, 1200), (10, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


def test_variants_are_webp_3_by_4_and_exif_free():
    processed = process_image(_jpeg_with_exif())
    thumb = Image.open(io.BytesIO(processed.variants["thumb"]))
    detail = Image.open(io.BytesIO(processed.variants["detail"]))
    assert thumb.format == "WEBP" and thumb.size == (400, 533)
    assert detail.size == (900, 1200)
    assert (processed.width, processed.height) == (900, 1200)
    assert "exif" not in detail.info


def test_small_images_are_not_upscaled():
    processed = process_image(png_bytes(300, 400))
    assert Image.open(io.BytesIO(processed.variants["thumb"])).size == (300, 400)


def test_garbage_is_rejected():
    with pytest.raises(InvalidImage) as exc:
        process_image(b"not an image")
    assert exc.value.code == "not_an_image"


def test_oversized_upload_is_rejected():
    with pytest.raises(InvalidImage) as exc:
        process_image(b"0" * (MAX_UPLOAD_BYTES + 1))
    assert exc.value.code == "too_large"


def test_save_style_image_writes_variants(db, tmp_path):
    storage = LocalStorage(tmp_path)
    style = make_style(db, make_shop(db))
    image = save_style_image(db, storage, style, png_bytes())
    assert image.position == 0
    assert (tmp_path / f"{image.storage_key}-thumb.webp").exists()
    assert (tmp_path / f"{image.storage_key}-detail.webp").exists()
    assert image_url(storage, image) == f"/media/{image.storage_key}-thumb.webp"


def test_style_image_limit(db, tmp_path):
    storage = LocalStorage(tmp_path)
    style = make_style(db, make_shop(db))
    for _ in range(MAX_IMAGES_PER_STYLE):
        save_style_image(db, storage, style, png_bytes(60, 80))
    with pytest.raises(InvalidImage) as exc:
        save_style_image(db, storage, style, png_bytes(60, 80))
    assert exc.value.code == "too_many"


def test_storage_refuses_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).put("../escape.txt", b"x", "text/plain")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_images.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.images'`.

- [ ] **Step 3: Implement images and storage**

`src/twirl/images.py`:

```python
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
VARIANTS = {"thumb": 400, "detail": 1200}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}
ASPECT = 3 / 4


class InvalidImage(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProcessedImage:
    variants: dict[str, bytes]
    width: int
    height: int


def _crop_to_aspect(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width / height > ASPECT:
        new_width = round(height * ASPECT)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = round(width / ASPECT)
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def process_image(data: bytes) -> ProcessedImage:
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImage("too_large")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types for bad input
        raise InvalidImage("not_an_image") from exc
    if image.format not in ALLOWED_FORMATS:
        raise InvalidImage("unsupported_format")
    image = _crop_to_aspect(ImageOps.exif_transpose(image).convert("RGB"))

    variants: dict[str, bytes] = {}
    detail_size = image.size
    for name, target_width in VARIANTS.items():
        width = min(target_width, image.width)
        height = round(width / ASPECT)
        resized = image.resize((width, height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        resized.save(buffer, "WEBP", quality=80, method=4)
        variants[name] = buffer.getvalue()
        if name == "detail":
            detail_size = (width, height)
    return ProcessedImage(variants=variants, width=detail_size[0], height=detail_size[1])
```

`src/twirl/storage.py`:

```python
from pathlib import Path
from typing import Protocol

from starlette.requests import Request


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def url(self, key: str) -> str: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Disk storage for development and the pilot. Swap for an R2 implementation later."""

    def __init__(self, root: Path, base_url: str = "/media") -> None:
        self.root = Path(root).resolve()
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("storage key escapes the root")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def get_storage(request: Request) -> Storage:
    return request.app.state.storage
```

Append to `src/twirl/catalog.py`:

```python
from uuid import uuid4  # noqa: E402

from twirl.images import InvalidImage, process_image  # noqa: E402
from twirl.models import StyleImage  # noqa: E402
from twirl.storage import Storage  # noqa: E402

MAX_IMAGES_PER_STYLE = 8


def save_style_image(session: Session, storage: Storage, style: Style, data: bytes) -> StyleImage:
    count = session.scalar(
        select(func.count()).select_from(StyleImage).where(StyleImage.style_id == style.id)
    ) or 0
    if count >= MAX_IMAGES_PER_STYLE:
        raise InvalidImage("too_many")
    processed = process_image(data)
    key = f"styles/{style.id}/{uuid4().hex}"
    for variant, blob in processed.variants.items():
        storage.put(f"{key}-{variant}.webp", blob, "image/webp")
    image = StyleImage(
        style_id=style.id, position=count, storage_key=key,
        width=processed.width, height=processed.height,
    )
    session.add(image)
    session.flush()
    return image


def image_url(storage: Storage, image: StyleImage, variant: str = "thumb") -> str:
    return storage.url(f"{image.storage_key}-{variant}.webp")
```

In `src/twirl/app.py`:
- add `from twirl.storage import LocalStorage` to the imports;
- in `create_app`, after `app.state.db = ...`, add:

```python
    settings.media_root.mkdir(parents=True, exist_ok=True)
    app.state.storage = LocalStorage(settings.media_root, "/media")
```

- after the `/static` mount, add:

```python
    app.mount("/media", StaticFiles(directory=settings.media_root), name="media")
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: image upload pipeline with WebP variants and local storage"
```

---

### Task 15: Shop catalog screens — dresses, photos, items, blocks, QR

**Files:**
- Create: `src/twirl/web/shop_catalog.py`
- Create: `src/twirl/templates/shop/styles.html`, `src/twirl/templates/shop/style_new.html`, `src/twirl/templates/shop/style_edit.html`, `src/twirl/templates/shop/_style_fields.html`
- Modify: `src/twirl/app.py`
- Test: `tests/test_shop_catalog.py`

**Interfaces:**
- Consumes: `create_style`, `add_items`, `save_style_image`, `image_url`, `size_sort_key`, `set_item_status`, `create_block`, `get_storage`, `require_shop`, `require_owner`, `verify_csrf`, `form_data`, `validate_form`, `render`, `N_`.
- Produces: routes `GET /shop/styles`, `GET|POST /shop/styles/new`, `GET|POST /shop/styles/{style_id}`, `POST /shop/styles/{style_id}/images`, `POST /shop/styles/{style_id}/items`, `POST /shop/items/{item_id}/status`, `POST /shop/items/{item_id}/block`, `GET /shop/items/{item_id}/qr.svg`. Style page reads `?error=<code>` with codes `block_conflict`, `block_dates`, `block_invalid`, `future_bookings`.

- [ ] **Step 1: Write the failing tests**

`tests/test_shop_catalog.py`:

```python
from datetime import timedelta

from sqlalchemy import func, select

from tests.factories import make_booking, make_item, make_shop, make_style
from tests.helpers import png_bytes, post
from twirl import clock
from twirl.models import Booking, Item, Style, StyleImage

T = clock.today()


def _style_data(**over):
    data = {"name": "Red silk gown", "price_eur": "55,50", "description": "",
            "occasion_tags": ["wedding", "matura"], "colour_family": "red", "length": "maxi",
            "published": "on"}
    data.update(over)
    return data


def test_owner_creates_style(owner_client, db, shop):
    response = post(owner_client, "/shop/styles/new", _style_data())
    assert response.status_code == 303
    style = db.scalars(select(Style).where(Style.shop_id == shop.id)).one()
    assert response.headers["location"] == f"/shop/styles/{style.id}"
    assert (style.code, style.price_cents, style.occasion_tags, style.colour_family, style.published) == (
        "001", 5550, ["wedding", "matura"], "red", True,
    )


def test_invalid_price_is_rejected(owner_client, db, shop):
    assert post(owner_client, "/shop/styles/new", _style_data(price_eur="abc")).status_code == 400
    assert db.scalar(select(func.count()).select_from(Style).where(Style.shop_id == shop.id)) == 0


def test_staff_cannot_create_styles(staff_client):
    assert staff_client.get("/shop/styles/new").status_code == 403


def test_owner_edits_style(owner_client, db, shop):
    style = make_style(db, shop, published=True)
    response = post(owner_client, f"/shop/styles/{style.id}", _style_data(name="New name", price_eur="60", published=""))
    assert response.status_code == 303
    assert (style.name, style.price_cents, style.published) == ("New name", 6000, False)


def test_staff_views_style_and_adds_items(staff_client, db, shop):
    style = make_style(db, shop)
    assert staff_client.get(f"/shop/styles/{style.id}").status_code == 200
    response = post(staff_client, f"/shop/styles/{style.id}/items", {"size": "38", "quantity": "2"})
    assert response.status_code == 303
    assert db.scalar(select(func.count()).select_from(Item).where(Item.style_id == style.id)) == 2


def test_photo_upload_is_processed_and_served(owner_client, db, shop, settings):
    style = make_style(db, shop)
    response = post(owner_client, f"/shop/styles/{style.id}/images",
                    files=[("files", ("a.png", png_bytes(), "image/png"))])
    assert response.status_code == 303
    image = db.scalars(select(StyleImage).where(StyleImage.style_id == style.id)).one()
    assert (settings.media_root / f"{image.storage_key}-thumb.webp").exists()
    assert owner_client.get(f"/media/{image.storage_key}-thumb.webp").status_code == 200


def test_garbage_upload_is_rejected(owner_client, db, shop):
    style = make_style(db, shop)
    response = post(owner_client, f"/shop/styles/{style.id}/images",
                    files=[("files", ("a.png", b"nope", "image/png"))])
    assert response.status_code == 400
    assert db.scalar(select(func.count()).select_from(StyleImage)) == 0


def test_other_shops_style_is_404(owner_client, db):
    style = make_style(db, make_shop(db))
    assert owner_client.get(f"/shop/styles/{style.id}").status_code == 404


def test_item_status_warns_about_future_bookings(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    make_booking(db, item, pickup=T + timedelta(days=5), return_=T + timedelta(days=6))
    response = post(owner_client, f"/shop/items/{item.id}/status", {"status": "repair"})
    assert response.status_code == 303
    assert response.headers["location"].endswith("?error=future_bookings")
    assert item.status == "repair"


def test_block_item_then_conflicting_block(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    data = {"starts_on": (T + timedelta(days=1)).isoformat(), "ends_on": (T + timedelta(days=2)).isoformat(),
            "reason": "repair"}
    assert post(owner_client, f"/shop/items/{item.id}/block", data).status_code == 303
    assert db.scalars(select(Booking).where(Booking.item_id == item.id)).one().kind == "block"
    second = post(owner_client, f"/shop/items/{item.id}/block", data)
    assert second.headers["location"].endswith("?error=block_conflict")


def test_item_qr_code(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    response = owner_client.get(f"/shop/items/{item.id}/qr.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_shop_catalog.py -v`
Expected: FAIL with 404 responses.

- [ ] **Step 3: Implement the catalog routes**

`src/twirl/web/shop_catalog.py`:

```python
import io
from datetime import date
from decimal import Decimal

import segno
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from twirl import clock
from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import ShopContext, require_owner, require_shop
from twirl.booking.errors import InvalidDates, ItemConflict
from twirl.booking.staff import create_block, set_item_status
from twirl.catalog import add_items, create_style, image_url, save_style_image, size_sort_key
from twirl.db import get_db
from twirl.i18n import N_
from twirl.images import MAX_UPLOAD_BYTES, InvalidImage
from twirl.models import ColourFamily, DressLength, Item, ItemStatus, Occasion, Style
from twirl.storage import Storage, get_storage
from twirl.web.forms import form_data, validate_form
from twirl.web.templating import render

router = APIRouter(prefix="/shop")

CHOICES = {
    "occasions": [
        (Occasion.WEDDING.value, N_("Wedding")), (Occasion.ENGAGEMENT.value, N_("Engagement")),
        (Occasion.MATURA.value, N_("Matura")), (Occasion.HENNA_NIGHT.value, N_("Henna night")),
        (Occasion.EVENING.value, N_("Evening")),
    ],
    "colours": [
        (ColourFamily.BLACK.value, N_("Black")), (ColourFamily.WHITE.value, N_("White")),
        (ColourFamily.RED.value, N_("Red")), (ColourFamily.PINK.value, N_("Pink")),
        (ColourFamily.BLUE.value, N_("Blue")), (ColourFamily.GREEN.value, N_("Green")),
        (ColourFamily.GOLD.value, N_("Gold")), (ColourFamily.SILVER.value, N_("Silver")),
        (ColourFamily.BEIGE.value, N_("Beige")), (ColourFamily.PURPLE.value, N_("Purple")),
        (ColourFamily.MULTI.value, N_("Multicolour")),
    ],
    "lengths": [
        (DressLength.MINI.value, N_("Short")), (DressLength.MIDI.value, N_("Midi")),
        (DressLength.MAXI.value, N_("Long")),
    ],
}
ITEM_STATUSES = [
    (ItemStatus.ACTIVE.value, N_("Available")), (ItemStatus.CLEANING.value, N_("Cleaning")),
    (ItemStatus.REPAIR.value, N_("Repair")), (ItemStatus.RETIRED.value, N_("Retired")),
    (ItemStatus.LOST.value, N_("Lost")),
]
PAGE_ERRORS = {
    "block_conflict": N_("That dress is already booked or blocked on those dates."),
    "block_dates": N_("The block end date must be on or after the start date."),
    "block_invalid": N_("Enter both dates and a reason for the block."),
    "future_bookings": N_("This dress still has upcoming bookings. Swap them to another dress."),
}
IMAGE_ERRORS = {
    "too_large": N_("That photo is larger than 15 MB."),
    "not_an_image": N_("That file is not a photo."),
    "unsupported_format": N_("Use JPEG, PNG or WebP photos."),
    "too_many": N_("A dress can have at most 8 photos."),
}


class StyleForm(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    price_eur: Decimal = Field(ge=0, le=5000, decimal_places=2)
    description: str = Field(default="", max_length=2000)
    occasion_tags: list[Occasion] = []
    colour_family: ColourFamily | None = None
    length: DressLength | None = None
    stretch: bool = False
    adjustable_back: bool = False
    published: bool = False

    @field_validator("price_eur", mode="before")
    @classmethod
    def _decimal_comma(cls, value):
        return value.replace(",", ".").strip() if isinstance(value, str) else value

    @field_validator("colour_family", "length", mode="before")
    @classmethod
    def _blank_is_none(cls, value):
        return value or None

    @field_validator("stretch", "adjustable_back", "published", mode="before")
    @classmethod
    def _checkbox(cls, value):
        return bool(value) and value not in ("off", "false", "0")

    @property
    def price_cents(self) -> int:
        return int(self.price_eur * 100)


class ItemsForm(BaseModel):
    size: str = Field(min_length=1, max_length=8)
    quantity: int = Field(ge=1, le=20)


class BlockForm(BaseModel):
    starts_on: date
    ends_on: date
    reason: str = Field(min_length=2, max_length=300)


def _get_style(db: Session, ctx: ShopContext, style_id: int) -> Style:
    style = db.get(Style, style_id)
    if style is None or style.shop_id != ctx.shop.id or style.deleted_at is not None:
        raise HTTPException(status_code=404)
    return style


def _get_item(db: Session, ctx: ShopContext, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None or item.shop_id != ctx.shop.id:
        raise HTTPException(status_code=404)
    return item


def _style_values(style: Style) -> dict:
    return {
        "name": style.name, "price_eur": f"{style.price_cents / 100:.2f}",
        "description": style.description, "occasion_tags": list(style.occasion_tags),
        "colour_family": style.colour_family or "", "length": style.length or "",
        "stretch": style.stretch, "adjustable_back": style.adjustable_back,
        "published": style.published,
    }


def _form_values(form: FormData) -> dict:
    return {
        "name": form.get("name", ""), "price_eur": form.get("price_eur", ""),
        "description": form.get("description", ""), "occasion_tags": form.getlist("occasion_tags"),
        "colour_family": form.get("colour_family", ""), "length": form.get("length", ""),
        "stretch": bool(form.get("stretch")), "adjustable_back": bool(form.get("adjustable_back")),
        "published": bool(form.get("published")),
    }


def _style_page(request: Request, ctx: ShopContext, style: Style, storage: Storage, *,
                values: dict | None = None, errors: dict | None = None, error: str | None = None,
                status_code: int = 200):
    return render(
        request, "shop/style_edit.html",
        {
            "ctx": ctx, "style": style,
            "items": sorted(style.items, key=lambda i: (size_sort_key(i.size), i.code)),
            "images": [image_url(storage, image) for image in style.images],
            "values": values or _style_values(style), "errors": errors or {}, "error": error,
            "choices": CHOICES, "item_statuses": ITEM_STATUSES,
        },
        status_code=status_code,
    )


def _apply(style_kwargs: StyleForm) -> dict:
    return {
        "name": style_kwargs.name.strip(),
        "price_cents": style_kwargs.price_cents,
        "description": style_kwargs.description.strip(),
        "occasion_tags": [tag.value for tag in style_kwargs.occasion_tags],
        "colour_family": style_kwargs.colour_family.value if style_kwargs.colour_family else None,
        "length": style_kwargs.length.value if style_kwargs.length else None,
        "stretch": style_kwargs.stretch,
        "adjustable_back": style_kwargs.adjustable_back,
        "published": style_kwargs.published,
    }


@router.get("/styles", response_class=HTMLResponse)
def list_styles(request: Request, ctx: ShopContext = Depends(require_shop),
                db: Session = Depends(get_db), storage: Storage = Depends(get_storage)):
    styles = db.scalars(
        select(Style).where(Style.shop_id == ctx.shop.id, Style.deleted_at.is_(None)).order_by(Style.code)
    ).all()
    rows = [
        {"style": s, "thumb": image_url(storage, s.images[0]) if s.images else None, "items": len(s.items)}
        for s in styles
    ]
    return render(request, "shop/styles.html", {"ctx": ctx, "rows": rows})


@router.get("/styles/new", response_class=HTMLResponse)
def new_style_form(request: Request, ctx: ShopContext = Depends(require_owner)):
    values = {"name": "", "price_eur": "", "description": "", "occasion_tags": [], "colour_family": "",
              "length": "", "stretch": False, "adjustable_back": False, "published": True}
    return render(request, "shop/style_new.html",
                  {"ctx": ctx, "values": values, "errors": {}, "choices": CHOICES})


@router.post("/styles/new", dependencies=[Depends(verify_csrf)])
def create_style_route(request: Request, form: FormData = Depends(form_data),
                       ctx: ShopContext = Depends(require_owner), db: Session = Depends(get_db)):
    parsed, errors = validate_form(StyleForm, form, list_fields=("occasion_tags",))
    if parsed is None:
        return render(request, "shop/style_new.html",
                      {"ctx": ctx, "values": _form_values(form), "errors": errors, "choices": CHOICES},
                      status_code=400)
    style = create_style(db, ctx.shop, **_apply(parsed))
    db.commit()
    return RedirectResponse(f"/shop/styles/{style.id}", status_code=303)


@router.get("/styles/{style_id}", response_class=HTMLResponse)
def style_page(request: Request, style_id: int, error: str | None = None,
               ctx: ShopContext = Depends(require_shop), db: Session = Depends(get_db),
               storage: Storage = Depends(get_storage)):
    style = _get_style(db, ctx, style_id)
    return _style_page(request, ctx, style, storage, error=PAGE_ERRORS.get(error or ""))


@router.post("/styles/{style_id}", dependencies=[Depends(verify_csrf)])
def update_style(request: Request, style_id: int, form: FormData = Depends(form_data),
                 ctx: ShopContext = Depends(require_owner), db: Session = Depends(get_db),
                 storage: Storage = Depends(get_storage)):
    style = _get_style(db, ctx, style_id)
    parsed, errors = validate_form(StyleForm, form, list_fields=("occasion_tags",))
    if parsed is None:
        return _style_page(request, ctx, style, storage, values=_form_values(form), errors=errors,
                           status_code=400)
    for field, value in _apply(parsed).items():
        setattr(style, field, value)
    db.commit()
    return RedirectResponse(f"/shop/styles/{style.id}", status_code=303)


@router.post("/styles/{style_id}/images", dependencies=[Depends(verify_csrf)])
def upload_images(request: Request, style_id: int, files: list[UploadFile] = File(...),
                  ctx: ShopContext = Depends(require_shop), db: Session = Depends(get_db),
                  storage: Storage = Depends(get_storage)):
    style = _get_style(db, ctx, style_id)
    failures = []
    for upload in files:
        try:
            save_style_image(db, storage, style, upload.file.read(MAX_UPLOAD_BYTES + 1))
        except InvalidImage as exc:
            failures.append(IMAGE_ERRORS.get(exc.code, IMAGE_ERRORS["not_an_image"]))
    db.commit()
    if failures:
        db.refresh(style)
        return _style_page(request, ctx, style, storage, error=failures[0], status_code=400)
    return RedirectResponse(f"/shop/styles/{style.id}", status_code=303)


@router.post("/styles/{style_id}/items", dependencies=[Depends(verify_csrf)])
def add_items_route(request: Request, style_id: int, form: FormData = Depends(form_data),
                    ctx: ShopContext = Depends(require_shop), db: Session = Depends(get_db),
                    storage: Storage = Depends(get_storage)):
    style = _get_style(db, ctx, style_id)
    parsed, _ = validate_form(ItemsForm, form)
    if parsed is None:
        return _style_page(request, ctx, style, storage,
                           error=N_("Enter a size and a quantity from 1 to 20."), status_code=400)
    add_items(db, style, size=parsed.size, quantity=parsed.quantity)
    db.commit()
    return RedirectResponse(f"/shop/styles/{style.id}", status_code=303)


@router.post("/items/{item_id}/status", dependencies=[Depends(verify_csrf)])
def item_status(item_id: int, form: FormData = Depends(form_data),
                ctx: ShopContext = Depends(require_shop), db: Session = Depends(get_db)):
    item = _get_item(db, ctx, item_id)
    try:
        future = set_item_status(db, item, str(form.get("status", "")), actor=ctx.actor, today=clock.today())
    except ValueError as exc:
        raise HTTPException(status_code=400) from exc
    db.commit()
    suffix = "?error=future_bookings" if future and item.status != ItemStatus.ACTIVE.value else ""
    return RedirectResponse(f"/shop/styles/{item.style_id}{suffix}", status_code=303)


@router.post("/items/{item_id}/block", dependencies=[Depends(verify_csrf)])
def block_item(item_id: int, form: FormData = Depends(form_data),
               ctx: ShopContext = Depends(require_shop), db: Session = Depends(get_db)):
    item = _get_item(db, ctx, item_id)
    target = f"/shop/styles/{item.style_id}"
    parsed, _ = validate_form(BlockForm, form)
    if parsed is None:
        return RedirectResponse(f"{target}?error=block_invalid", status_code=303)
    try:
        create_block(db, item=item, starts_on=parsed.starts_on, ends_on=parsed.ends_on,
                     reason=parsed.reason, actor=ctx.actor)
    except ItemConflict:
        db.rollback()
        return RedirectResponse(f"{target}?error=block_conflict", status_code=303)
    except InvalidDates:
        db.rollback()
        return RedirectResponse(f"{target}?error=block_dates", status_code=303)
    db.commit()
    return RedirectResponse(target, status_code=303)


@router.get("/items/{item_id}/qr.svg")
def item_qr(request: Request, item_id: int, ctx: ShopContext = Depends(require_shop),
            db: Session = Depends(get_db)):
    item = _get_item(db, ctx, item_id)
    url = f"{request.app.state.settings.base_url}/shop/walk-in?code={item.code}"
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="svg", scale=4)
    return Response(buffer.getvalue(), media_type="image/svg+xml")
```

- [ ] **Step 4: Add the templates**

`src/twirl/templates/shop/_style_fields.html`:

```html
<label>{{ _("Name") }} <input name="name" value="{{ values.name }}" required maxlength="160">
  {% if errors.name %}<span class="error">{{ errors.name }}</span>{% endif %}</label>
<label>{{ _("Price per rental (€)") }} <input name="price_eur" inputmode="decimal" value="{{ values.price_eur }}" required>
  {% if errors.price_eur %}<span class="error">{{ errors.price_eur }}</span>{% endif %}</label>
<label>{{ _("Description") }} <textarea name="description" rows="3" maxlength="2000">{{ values.description }}</textarea></label>
<fieldset><legend>{{ _("Occasions") }}</legend>
  {% for value, label in choices.occasions %}
  <label class="inline"><input type="checkbox" name="occasion_tags" value="{{ value }}"
    {% if value in values.occasion_tags %}checked{% endif %}> {{ _(label) }}</label>
  {% endfor %}
</fieldset>
<label>{{ _("Colour") }} <select name="colour_family"><option value="">—</option>
  {% for value, label in choices.colours %}<option value="{{ value }}" {% if values.colour_family == value %}selected{% endif %}>{{ _(label) }}</option>{% endfor %}
</select></label>
<label>{{ _("Length") }} <select name="length"><option value="">—</option>
  {% for value, label in choices.lengths %}<option value="{{ value }}" {% if values.length == value %}selected{% endif %}>{{ _(label) }}</option>{% endfor %}
</select></label>
<label class="inline"><input type="checkbox" name="stretch" {% if values.stretch %}checked{% endif %}> {{ _("Stretch fabric") }}</label>
<label class="inline"><input type="checkbox" name="adjustable_back" {% if values.adjustable_back %}checked{% endif %}> {{ _("Adjustable back") }}</label>
<label class="inline"><input type="checkbox" name="published" {% if values.published %}checked{% endif %}> {{ _("Show on my storefront") }}</label>
```

`src/twirl/templates/shop/style_new.html`:

```html
{% extends "shop/base.html" %}
{% block content %}
<h1>{{ _("New dress") }}</h1>
<form method="post" action="/shop/styles/new">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  {% include "shop/_style_fields.html" %}
  <button>{{ _("Create") }}</button>
</form>
{% endblock %}
```

`src/twirl/templates/shop/styles.html`:

```html
{% extends "shop/base.html" %}
{% block content %}
<h1>{{ _("Dresses") }}</h1>
{% if ctx.is_owner %}<p><a href="/shop/styles/new">{{ _("Add a dress") }}</a></p>{% endif %}
<table>
  <thead><tr><th></th><th>{{ _("Name") }}</th><th>{{ _("Price") }}</th><th>{{ _("Pieces") }}</th><th>{{ _("Online") }}</th></tr></thead>
  <tbody>
  {% for row in rows %}
    <tr>
      <td>{% if row.thumb %}<img src="{{ row.thumb }}" alt="{{ row.style.name }}" width="60" height="80" loading="lazy">{% endif %}</td>
      <td><a href="/shop/styles/{{ row.style.id }}">{{ row.style.name }}</a> <small>#{{ row.style.code }}</small></td>
      <td>{{ row.style.price_cents|money(locale) }}</td>
      <td>{{ row.items }}</td>
      <td>{{ _("Yes") if row.style.published else _("No") }}</td>
    </tr>
  {% else %}
    <tr><td colspan="5" class="muted">{{ _("No dresses yet.") }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`src/twirl/templates/shop/style_edit.html`:

```html
{% extends "shop/base.html" %}
{% block content %}
<p><a href="/shop/styles">← {{ _("All dresses") }}</a></p>
<h1>{{ style.name }} <small>#{{ style.code }}</small></h1>
{% if error %}<p class="error" role="alert">{{ _(error) }}</p>{% endif %}

{% if ctx.is_owner %}
<form method="post" action="/shop/styles/{{ style.id }}">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  {% include "shop/_style_fields.html" %}
  <button>{{ _("Save") }}</button>
</form>
{% else %}
<p>{{ style.price_cents|money(locale) }}</p>
{% endif %}

<h2>{{ _("Photos") }}</h2>
<div class="photos">
  {% for url in images %}<img src="{{ url }}" alt="{{ style.name }}" width="120" height="160" loading="lazy">{% endfor %}
</div>
<form method="post" action="/shop/styles/{{ style.id }}/images" enctype="multipart/form-data">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  <input type="file" name="files" accept="image/*" multiple required>
  <button>{{ _("Upload photos") }}</button>
</form>

<h2>{{ _("Physical dresses") }}</h2>
<table>
  <thead><tr><th>{{ _("Code") }}</th><th>{{ _("Size") }}</th><th>{{ _("Status") }}</th><th>{{ _("Block dates") }}</th><th>QR</th></tr></thead>
  <tbody>
  {% for item in items %}
    <tr>
      <td><strong>{{ item.code }}</strong></td>
      <td>{{ item.size }}</td>
      <td>
        <form method="post" action="/shop/items/{{ item.id }}/status" class="inline">
          <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
          <select name="status">
            {% for value, label in item_statuses %}<option value="{{ value }}" {% if item.status == value %}selected{% endif %}>{{ _(label) }}</option>{% endfor %}
          </select>
          <button>{{ _("Set") }}</button>
        </form>
      </td>
      <td>
        <form method="post" action="/shop/items/{{ item.id }}/block" class="inline">
          <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
          <input type="date" name="starts_on" required aria-label="{{ _('From') }}">
          <input type="date" name="ends_on" required aria-label="{{ _('To') }}">
          <input name="reason" required placeholder="{{ _('Reason') }}" aria-label="{{ _('Reason') }}">
          <button>{{ _("Block") }}</button>
        </form>
      </td>
      <td><a href="/shop/items/{{ item.id }}/qr.svg">QR</a></td>
    </tr>
  {% else %}
    <tr><td colspan="5" class="muted">{{ _("No physical dresses yet. Add them below.") }}</td></tr>
  {% endfor %}
  </tbody>
</table>

<form method="post" action="/shop/styles/{{ style.id }}/items">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  <label>{{ _("Size") }} <input name="size" required maxlength="8"></label>
  <label>{{ _("How many of this size") }} <input type="number" name="quantity" value="1" min="1" max="20"></label>
  <button>{{ _("Add dresses") }}</button>
</form>
{% endblock %}
```

In `src/twirl/app.py`, add `shop_catalog` to the `from twirl.web import ...` line and `shop_catalog.router` to the router tuple.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_shop_catalog.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: shop catalog screens with photo upload, items, blocks and QR tags"
```

---

### Task 16: Shop booking screens — Today, booking actions, walk-in, calendar

**Files:**
- Create: `src/twirl/booking/board.py`, `src/twirl/web/messages.py`, `src/twirl/web/shop_bookings.py`
- Create: `src/twirl/templates/shop/_macros.html`, `src/twirl/templates/shop/booking.html`, `src/twirl/templates/shop/walk_in.html`, `src/twirl/templates/shop/calendar.html`
- Replace: `src/twirl/templates/shop/today.html`
- Delete: `src/twirl/web/shop_home.py`
- Modify: `src/twirl/app.py`
- Test: `tests/test_board.py`, `tests/test_shop_bookings.py`

**Interfaces:**
- Consumes: staff operations (Task 9), `create_request` (Task 8, tests only), `require_shop`, `verify_csrf`, `form_data`, `validate_form`, `render`.
- Produces: `TodayBoard`, `today_board(session, shop_id, today) -> TodayBoard`, `CalendarRow(item, cells)`, `week_calendar(session, shop_id, start) -> tuple[list[date], list[CalendarRow]]`; `STATUS_LABELS`, `DATE_ERRORS` in `twirl.web.messages`; routes `GET /shop`, `GET /shop/bookings/{id}`, `POST /shop/bookings/{id}/{action}` (actions: `accept`, `decline`, `picked-up`, `returned-ok`, `returned-issue`, `no-show`, `cancel`, `swap`), `GET|POST /shop/walk-in`, `GET /shop/calendar`.

- [ ] **Step 1: Write the failing tests**

`tests/test_board.py`:

```python
from datetime import timedelta

from tests.factories import make_booking, make_item, make_shop, make_style
from twirl import clock
from twirl.booking.board import today_board, week_calendar

T = clock.today()


def test_today_board_groups_bookings(db):
    shop = make_shop(db)
    style = make_style(db, shop)
    items = [make_item(db, style) for _ in range(6)]
    pending = make_booking(db, items[0], pickup=T + timedelta(days=9), return_=T + timedelta(days=10),
                           kind="online", status="pending_shop")
    pickup = make_booking(db, items[1], pickup=T, return_=T + timedelta(days=2))
    returning = make_booking(db, items[2], pickup=T - timedelta(days=2), return_=T, status="picked_up")
    overdue = make_booking(db, items[3], pickup=T - timedelta(days=1), return_=T + timedelta(days=1))
    at_risk = make_booking(db, items[4], pickup=T + timedelta(days=3), return_=T + timedelta(days=4),
                           kind="online", status="at_risk")
    make_booking(db, items[5], pickup=T, return_=T, kind="block")
    board = today_board(db, shop.id, T)
    assert [b.id for b in board.pending] == [pending.id]
    assert [b.id for b in board.pickups_today] == [pickup.id]
    assert [b.id for b in board.returns_today] == [returning.id]
    assert [b.id for b in board.overdue_pickups] == [overdue.id]
    assert [b.id for b in board.at_risk] == [at_risk.id]


def test_week_calendar_places_bookings_including_cleaning_day(db):
    shop = make_shop(db)
    item = make_item(db, make_style(db, shop))
    booking = make_booking(db, item, pickup=T + timedelta(days=1), return_=T + timedelta(days=2), cleaning_days=1)
    days, rows = week_calendar(db, shop.id, T)
    assert len(days) == 7 and days[0] == T
    cells = rows[0].cells
    assert [c.id if c else None for c in cells[:5]] == [None, booking.id, booking.id, booking.id, None]
```

`tests/test_shop_bookings.py`:

```python
from datetime import timedelta

from sqlalchemy import select

from tests.factories import make_booking, make_item, make_renter, make_shop, make_style
from tests.helpers import post
from twirl import clock
from twirl.booking.requests import RentalRequest, create_request
from twirl.models import Booking

T = clock.today()


def _pending(db, shop):
    style = make_style(db, shop)
    make_item(db, style, size="38")
    return create_request(
        db, RentalRequest(style_id=style.id, size="38", event_date=T + timedelta(days=20),
                          name="Arta", phone="044 123 456"),
        today=T,
    )


def test_today_lists_pending_requests(owner_client, db, shop):
    booking = _pending(db, shop)
    response = owner_client.get("/shop")
    assert response.status_code == 200
    assert booking.ref in response.text


def test_booking_page_offers_accept(owner_client, db, shop):
    booking = _pending(db, shop)
    response = owner_client.get(f"/shop/bookings/{booking.id}")
    assert response.status_code == 200
    assert f'/shop/bookings/{booking.id}/accept' in response.text


def test_accept_request(owner_client, db, shop):
    booking = _pending(db, shop)
    assert post(owner_client, f"/shop/bookings/{booking.id}/accept").status_code == 303
    assert booking.status == "confirmed"


def test_decline_needs_a_reason(owner_client, db, shop):
    booking = _pending(db, shop)
    assert post(owner_client, f"/shop/bookings/{booking.id}/decline").status_code == 400
    assert post(owner_client, f"/shop/bookings/{booking.id}/decline", {"reason": "damaged"}).status_code == 303
    assert (booking.status, booking.reason) == ("declined", "damaged")


def test_impossible_action_is_409(owner_client, db, shop):
    booking = _pending(db, shop)
    assert post(owner_client, f"/shop/bookings/{booking.id}/picked-up").status_code == 409
    db.refresh(booking)
    assert booking.status == "pending_shop"


def test_other_shops_booking_is_404(owner_client, db):
    booking = _pending(db, make_shop(db))
    assert owner_client.get(f"/shop/bookings/{booking.id}").status_code == 404
    assert post(owner_client, f"/shop/bookings/{booking.id}/accept").status_code == 404


def _walk_in_data(item, **over):
    data = {"code": item.code.lower(), "kind": "walk_in", "pickup_date": T.isoformat(),
            "return_date": (T + timedelta(days=2)).isoformat(), "name": "Blerta",
            "phone": "044 555 666", "picked_up_now": "on"}
    data.update(over)
    return data


def test_walk_in_form_prefills_code(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    response = owner_client.get(f"/shop/walk-in?code={item.code}")
    assert response.status_code == 200
    assert f'value="{item.code}"' in response.text


def test_walk_in_created_and_picked_up(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    response = post(owner_client, "/shop/walk-in", _walk_in_data(item))
    assert response.status_code == 303
    booking = db.scalars(select(Booking).where(Booking.item_id == item.id)).one()
    assert (booking.kind, booking.status) == ("walk_in", "picked_up")


def test_walk_in_conflict_offers_override(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    online = make_booking(db, item, pickup=T + timedelta(days=5), return_=T + timedelta(days=7),
                          kind="online", status="confirmed", customer=make_renter(db))
    data = _walk_in_data(item, pickup_date=(T + timedelta(days=5)).isoformat(),
                         return_date=(T + timedelta(days=6)).isoformat(), picked_up_now="")
    first = post(owner_client, "/shop/walk-in", data)
    assert first.status_code == 409
    assert online.ref in first.text
    assert 'name="override_reason"' in first.text
    second = post(owner_client, "/shop/walk-in", {**data, "override_reason": "paid cash"})
    assert second.status_code == 303
    db.refresh(online)
    assert online.status == "at_risk"


def test_walk_in_unknown_code(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    assert post(owner_client, "/shop/walk-in", _walk_in_data(item, code="ZZZZ")).status_code == 400


def test_swap_via_route(owner_client, db, shop):
    style = make_style(db, shop)
    item, other = make_item(db, style), make_item(db, style)
    booking = make_booking(db, item, pickup=T + timedelta(days=3), return_=T + timedelta(days=4),
                           kind="online", status="at_risk")
    response = post(owner_client, f"/shop/bookings/{booking.id}/swap", {"item_id": str(other.id)})
    assert response.status_code == 303
    db.refresh(booking)
    assert (booking.item_id, booking.status) == (other.id, "confirmed")


def test_calendar_shows_block(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    make_booking(db, item, pickup=T + timedelta(days=1), return_=T + timedelta(days=2), kind="block",
                 cleaning_days=0)
    response = owner_client.get(f"/shop/calendar?start={T.isoformat()}")
    assert response.status_code == 200
    assert item.code in response.text
    assert 'data-kind="block"' in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_board.py tests/test_shop_bookings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.booking.board'`.

- [ ] **Step 3: Implement the board and calendar queries**

`src/twirl/booking/board.py`:

```python
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session, joinedload

from twirl.models import (
    ACTIVE_STATUSES, Booking, BookingKind, BookingStatus, Item, ItemStatus, Style,
)


@dataclass
class TodayBoard:
    pending: list[Booking]
    at_risk: list[Booking]
    pickups_today: list[Booking]
    returns_today: list[Booking]
    overdue_pickups: list[Booking]
    overdue_returns: list[Booking]


def _bookings(session: Session, shop_id: int, *conditions, order=Booking.pickup_date) -> list[Booking]:
    stmt = (
        select(Booking)
        .where(Booking.shop_id == shop_id, Booking.kind != BookingKind.BLOCK.value, *conditions)
        .options(joinedload(Booking.item), joinedload(Booking.style), joinedload(Booking.customer))
        .order_by(order, Booking.id)
    )
    return list(session.scalars(stmt).unique())


def today_board(session: Session, shop_id: int, today: date) -> TodayBoard:
    s = BookingStatus
    return TodayBoard(
        pending=_bookings(session, shop_id, Booking.status == s.PENDING_SHOP.value, order=Booking.created_at),
        at_risk=_bookings(session, shop_id, Booking.status == s.AT_RISK.value),
        pickups_today=_bookings(session, shop_id, Booking.status == s.CONFIRMED.value, Booking.pickup_date == today),
        returns_today=_bookings(session, shop_id, Booking.status == s.PICKED_UP.value, Booking.return_date == today),
        overdue_pickups=_bookings(session, shop_id, Booking.status == s.CONFIRMED.value, Booking.pickup_date < today),
        overdue_returns=_bookings(
            session, shop_id,
            Booking.status.in_([s.PICKED_UP.value, s.NOT_RETURNED.value]), Booking.return_date < today,
        ),
    )


@dataclass
class CalendarRow:
    item: Item
    cells: list[Booking | None]


def week_calendar(session: Session, shop_id: int, start: date) -> tuple[list[date], list[CalendarRow]]:
    days = [start + timedelta(days=i) for i in range(7)]
    items = session.scalars(
        select(Item)
        .join(Style, Style.id == Item.style_id)
        .where(Item.shop_id == shop_id, Item.status != ItemStatus.RETIRED.value, Style.deleted_at.is_(None))
        .options(joinedload(Item.style))
        .order_by(Style.code, Item.size, Item.code)
    ).all()
    bookings = session.scalars(
        select(Booking).where(
            Booking.shop_id == shop_id,
            Booking.status.in_(ACTIVE_STATUSES),
            Booking.blocked_range.overlaps(Range(days[0], days[-1], bounds="[]")),
        )
    ).all()
    by_item: dict[int, list[Booking]] = defaultdict(list)
    for booking in bookings:
        by_item[booking.item_id].append(booking)
    rows = []
    for item in items:
        cells = [
            next(
                (b for b in by_item[item.id] if b.blocked_range.lower <= day < b.blocked_range.upper),
                None,
            )
            for day in days
        ]
        rows.append(CalendarRow(item=item, cells=cells))
    return days, rows
```

- [ ] **Step 4: Implement messages and the booking routes**

`src/twirl/web/messages.py`:

```python
from twirl.i18n import N_

STATUS_LABELS = {
    "hold": N_("On hold"),
    "pending_shop": N_("Waiting for your answer"),
    "confirmed": N_("Confirmed"),
    "at_risk": N_("At risk"),
    "picked_up": N_("Picked up"),
    "completed": N_("Returned"),
    "cancelled_by_renter": N_("Cancelled by customer"),
    "cancelled_by_shop": N_("Cancelled by shop"),
    "expired": N_("Expired"),
    "no_show": N_("No-show"),
    "not_returned": N_("Not returned"),
    "declined": N_("Declined"),
}

DATE_ERRORS = {
    "pickup_in_past": N_("That date is too soon for this shop. Pick a later date."),
    "return_before_pickup": N_("The return date must be on or after the pickup date."),
    "too_long": N_("That rental is longer than this shop allows."),
    "event_outside_rental": N_("The event date must fall between pickup and return."),
    "pickup_closed": N_("The shop is closed on the pickup day."),
    "return_closed": N_("The shop is closed on the return day."),
    "no_open_day": N_("The shop is closed around that date."),
}
GENERIC_DATE_ERROR = N_("Those dates do not work for this shop.")
```

`src/twirl/web/shop_bookings.py`:

```python
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from twirl import clock
from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import ShopContext, require_shop
from twirl.booking import staff
from twirl.booking.board import today_board, week_calendar
from twirl.booking.errors import InvalidDates, InvalidTransition, ItemConflict
from twirl.db import get_db
from twirl.i18n import N_
from twirl.models import Booking, BookingEvent, BookingKind, Item
from twirl.phones import InvalidPhone
from twirl.web.forms import form_data, validate_form
from twirl.web.messages import DATE_ERRORS, GENERIC_DATE_ERROR, STATUS_LABELS
from twirl.web.templating import render

router = APIRouter(prefix="/shop")

ACTIONS = {
    "pending_shop": [("accept", N_("Accept"), False), ("decline", N_("Decline"), True)],
    "confirmed": [("picked-up", N_("Picked up"), False), ("no-show", N_("No-show"), False),
                  ("cancel", N_("Cancel"), True)],
    "at_risk": [("cancel", N_("Cancel"), True)],
    "picked_up": [("returned-ok", N_("Returned OK"), False),
                  ("returned-issue", N_("Returned with an issue"), True)],
    "not_returned": [("returned-ok", N_("Returned OK"), False),
                     ("returned-issue", N_("Returned with an issue"), True)],
}
BLOCK_ACTIONS = [("cancel", N_("Remove block"), False)]
REASON_ACTIONS = {"decline", "cancel", "returned-issue"}


class WalkInForm(BaseModel):
    code: str = Field(min_length=4, max_length=4)
    kind: Literal["walk_in", "phone"] = "walk_in"
    pickup_date: date
    return_date: date
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=30)
    note: str = Field(default="", max_length=500)
    picked_up_now: bool = False
    override_reason: str = Field(default="", max_length=300)

    @field_validator("code", mode="before")
    @classmethod
    def _upper(cls, value):
        return str(value or "").strip().upper()

    @field_validator("picked_up_now", mode="before")
    @classmethod
    def _checkbox(cls, value):
        return bool(value) and value not in ("off", "false", "0")


def _get_booking(db: Session, ctx: ShopContext, booking_id: int) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.shop_id != ctx.shop.id:
        raise HTTPException(status_code=404)
    return booking


def _booking_page(request: Request, db: Session, ctx: ShopContext, booking: Booking, *,
                  error: str | None = None, status_code: int = 200):
    events = db.scalars(
        select(BookingEvent).where(BookingEvent.booking_id == booking.id).order_by(BookingEvent.id)
    ).all()
    is_block = booking.kind == BookingKind.BLOCK.value
    if is_block:
        actions = BLOCK_ACTIONS if booking.status == "confirmed" else []
    else:
        actions = ACTIONS.get(booking.status, [])
    candidates = (
        staff.swap_candidates(db, booking)
        if not is_block and booking.status in staff.SWAPPABLE else []
    )
    return render(
        request, "shop/booking.html",
        {"ctx": ctx, "b": booking, "events": events, "actions": actions, "candidates": candidates,
         "error": error, "status_labels": STATUS_LABELS},
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def today(request: Request, ctx: ShopContext = Depends(require_shop), db: Session = Depends(get_db)):
    day = clock.today()
    return render(request, "shop/today.html",
                  {"ctx": ctx, "board": today_board(db, ctx.shop.id, day), "today": day})


@router.get("/bookings/{booking_id}", response_class=HTMLResponse)
def booking_detail(request: Request, booking_id: int, ctx: ShopContext = Depends(require_shop),
                   db: Session = Depends(get_db)):
    return _booking_page(request, db, ctx, _get_booking(db, ctx, booking_id))


@router.post("/bookings/{booking_id}/{action}", dependencies=[Depends(verify_csrf)])
def booking_action(request: Request, booking_id: int, action: str,
                   form: FormData = Depends(form_data), ctx: ShopContext = Depends(require_shop),
                   db: Session = Depends(get_db)):
    booking = _get_booking(db, ctx, booking_id)
    reason = str(form.get("reason") or "")
    actor = ctx.actor
    try:
        match action:
            case "accept":
                staff.accept(db, booking, actor)
            case "decline":
                staff.decline(db, booking, actor, reason)
            case "picked-up":
                staff.mark_picked_up(db, booking, actor)
            case "returned-ok":
                staff.mark_returned(db, booking, actor, ok=True, note=reason)
            case "returned-issue":
                staff.mark_returned(db, booking, actor, ok=False, note=reason)
            case "no-show":
                staff.mark_no_show(db, booking, actor)
            case "cancel":
                if booking.kind == BookingKind.BLOCK.value:
                    staff.cancel_block(db, booking, actor)
                else:
                    staff.cancel_by_shop(db, booking, actor, reason)
            case "swap":
                item_id = str(form.get("item_id") or "")
                item = db.get(Item, int(item_id)) if item_id.isdigit() else None
                if item is None or item.shop_id != ctx.shop.id:
                    raise HTTPException(status_code=404)
                staff.swap_item(db, booking, item, actor=actor)
            case _:
                raise HTTPException(status_code=404)
    except (InvalidTransition, ItemConflict) as exc:
        db.rollback()
        message = (
            N_("That dress is taken on these dates. Pick another one.")
            if isinstance(exc, ItemConflict)
            else N_("That action is not possible for this booking any more.")
        )
        return _booking_page(request, db, ctx, booking, error=message, status_code=409)
    except ValueError:
        db.rollback()
        message = (
            N_("Please give a reason.") if action in REASON_ACTIONS
            else N_("Check the form and try again.")
        )
        return _booking_page(request, db, ctx, booking, error=message, status_code=400)
    db.commit()
    return RedirectResponse(f"/shop/bookings/{booking.id}", status_code=303)


def _walk_in_page(request: Request, db: Session, ctx: ShopContext, values: dict, *,
                  error: str | None = None, errors: dict | None = None, conflicts=None,
                  overridable: bool = False, status_code: int = 200):
    item = staff.find_item_by_code(db, ctx.shop.id, values["code"]) if len(values["code"]) == 4 else None
    return render(
        request, "shop/walk_in.html",
        {"ctx": ctx, "values": values, "item": item, "error": error, "errors": errors or {},
         "conflicts": conflicts or [], "overridable": overridable, "status_labels": STATUS_LABELS},
        status_code=status_code,
    )


@router.get("/walk-in", response_class=HTMLResponse)
def walk_in_form(request: Request, code: str = "", ctx: ShopContext = Depends(require_shop),
                 db: Session = Depends(get_db)):
    day = clock.today()
    values = {"code": code.strip().upper(), "kind": "walk_in", "pickup_date": day.isoformat(),
              "return_date": (day + timedelta(days=2)).isoformat(), "name": "", "phone": "",
              "note": "", "picked_up_now": True, "override_reason": ""}
    return _walk_in_page(request, db, ctx, values)


@router.post("/walk-in", dependencies=[Depends(verify_csrf)])
def create_walk_in(request: Request, form: FormData = Depends(form_data),
                   ctx: ShopContext = Depends(require_shop), db: Session = Depends(get_db)):
    keys = ("code", "kind", "pickup_date", "return_date", "name", "phone", "note", "override_reason")
    values = {key: str(form.get(key) or "") for key in keys}
    values["code"] = values["code"].strip().upper()
    values["picked_up_now"] = bool(form.get("picked_up_now"))
    parsed, errors = validate_form(WalkInForm, form)
    if parsed is None:
        return _walk_in_page(request, db, ctx, values, errors=errors,
                             error=N_("Check the highlighted fields."), status_code=400)
    item = staff.find_item_by_code(db, ctx.shop.id, parsed.code)
    if item is None:
        return _walk_in_page(request, db, ctx, values,
                             error=N_("No dress with this code in your shop."), status_code=400)
    try:
        booking = staff.create_staff_booking(
            db, shop=ctx.shop, item=item, pickup=parsed.pickup_date, return_=parsed.return_date,
            name=parsed.name, phone=parsed.phone, actor=ctx.actor, kind=BookingKind(parsed.kind),
            picked_up_now=parsed.picked_up_now, override_reason=parsed.override_reason or None,
            note=parsed.note,
        )
    except ItemConflict as exc:
        db.rollback()
        return _walk_in_page(request, db, ctx, values, conflicts=exc.conflicts,
                             overridable=exc.overridable,
                             error=N_("This dress is already booked on those dates."), status_code=409)
    except InvalidPhone:
        db.rollback()
        return _walk_in_page(request, db, ctx, values,
                             error=N_("That phone number does not look right."), status_code=400)
    except InvalidDates as exc:
        db.rollback()
        return _walk_in_page(request, db, ctx, values,
                             error=DATE_ERRORS.get(exc.code, GENERIC_DATE_ERROR), status_code=400)
    db.commit()
    return RedirectResponse(f"/shop/bookings/{booking.id}", status_code=303)


@router.get("/calendar", response_class=HTMLResponse)
def calendar(request: Request, start: date | None = None, ctx: ShopContext = Depends(require_shop),
             db: Session = Depends(get_db)):
    first = start or clock.today()
    days, rows = week_calendar(db, ctx.shop.id, first)
    return render(
        request, "shop/calendar.html",
        {"ctx": ctx, "days": days, "rows": rows,
         "prev": (first - timedelta(days=7)).isoformat(), "next": (first + timedelta(days=7)).isoformat()},
    )
```

- [ ] **Step 5: Add the templates**

`src/twirl/templates/shop/_macros.html`:

```html
{% macro booking_list(title, bookings, empty) %}
<section>
  <h2>{{ title }} ({{ bookings|length }})</h2>
  {% if bookings %}
  <ul class="bookings">
    {% for b in bookings %}
    <li><a href="/shop/bookings/{{ b.id }}"><strong>{{ b.ref }}</strong>
      · {{ b.style.name }} {{ b.item.size }} ({{ b.item.code }})
      {% if b.customer %}· {{ b.customer.name }}{% endif %}
      · {{ b.pickup_date|date }} – {{ b.return_date|date }}</a></li>
    {% endfor %}
  </ul>
  {% else %}
  <p class="muted">{{ empty }}</p>
  {% endif %}
</section>
{% endmacro %}
```

`src/twirl/templates/shop/today.html`:

```html
{% extends "shop/base.html" %}
{% block content %}
{% from "shop/_macros.html" import booking_list %}
<h1>{{ ctx.shop.name }} · {{ today|date }}</h1>
<p><a href="/shop/walk-in">{{ _("New walk-in") }}</a></p>
{{ booking_list(_("Requests waiting for you"), board.pending, _("No requests waiting.")) }}
{{ booking_list(_("At risk: find another dress"), board.at_risk, _("Nothing at risk.")) }}
{{ booking_list(_("Pickups today"), board.pickups_today, _("No pickups today.")) }}
{{ booking_list(_("Returns today"), board.returns_today, _("No returns today.")) }}
{{ booking_list(_("Overdue pickups"), board.overdue_pickups, _("None.")) }}
{{ booking_list(_("Overdue returns"), board.overdue_returns, _("None.")) }}
{% endblock %}
```

`src/twirl/templates/shop/booking.html`:

```html
{% extends "shop/base.html" %}
{% block content %}
<h1>{{ b.ref }} · {{ _(status_labels[b.status]) }}</h1>
{% if error %}<p class="error" role="alert">{{ _(error) }}</p>{% endif %}
<dl>
  <dt>{{ _("Dress") }}</dt><dd>{{ b.style.name }} · {{ _("size") }} {{ b.item.size }} · {{ _("code") }} {{ b.item.code }}</dd>
  {% if b.customer %}<dt>{{ _("Customer") }}</dt><dd>{{ b.customer.name }} · <a href="tel:{{ b.customer.phone }}">{{ b.customer.phone }}</a></dd>{% endif %}
  {% if b.event_date %}<dt>{{ _("Event") }}</dt><dd>{{ b.event_date|date }}</dd>{% endif %}
  <dt>{{ _("Pickup") }}</dt><dd>{{ b.pickup_date|date }}</dd>
  <dt>{{ _("Return") }}</dt><dd>{{ b.return_date|date }}</dd>
  {% if b.kind != "block" %}<dt>{{ _("Price") }}</dt><dd>{{ b.price_cents|money(locale) }}</dd>{% endif %}
  {% if b.customer_note %}<dt>{{ _("Note from the customer") }}</dt><dd>{{ b.customer_note }}</dd>{% endif %}
  {% if b.reason %}<dt>{{ _("Reason") }}</dt><dd>{{ b.reason }}</dd>{% endif %}
</dl>

<div class="actions">
{% for action, label, needs_reason in actions %}
  <form method="post" action="/shop/bookings/{{ b.id }}/{{ action }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
    {% if needs_reason %}<label>{{ _("Reason") }} <input name="reason" required maxlength="300"></label>{% endif %}
    <button>{{ _(label) }}</button>
  </form>
{% endfor %}
</div>

{% if candidates %}
<h2>{{ _("Move to another dress") }}</h2>
<form method="post" action="/shop/bookings/{{ b.id }}/swap">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  <select name="item_id">
    {% for item in candidates %}<option value="{{ item.id }}">{{ item.style.name }} · {{ item.size }} · {{ item.code }}</option>{% endfor %}
  </select>
  <button>{{ _("Move") }}</button>
</form>
{% endif %}

<h2>{{ _("History") }}</h2>
<ol class="timeline">
  {% for e in events %}
  <li>{{ e.created_at.strftime("%d.%m.%Y %H:%M") }} ·
    {{ _(status_labels[e.from_status]) if e.from_status else "—" }} → {{ _(status_labels[e.to_status]) }}
    {% if e.reason %}· {{ e.reason }}{% endif %}</li>
  {% endfor %}
</ol>
{% endblock %}
```

`src/twirl/templates/shop/walk_in.html`:

```html
{% extends "shop/base.html" %}
{% block content %}
<h1>{{ _("Walk-in or phone booking") }}</h1>
{% if error %}<p class="error" role="alert">{{ _(error) }}</p>{% endif %}
{% if item %}<p>{{ item.style.name }} · {{ _("size") }} {{ item.size }}</p>{% endif %}

{% if conflicts %}
<ul class="conflicts">
  {% for c in conflicts %}
  <li><strong>{{ c.ref }}</strong> · {{ _(status_labels[c.status]) }} · {{ c.pickup_date|date }} – {{ c.return_date|date }}
    {% if c.customer %}· {{ c.customer.name }} {{ c.customer.phone }}{% endif %}</li>
  {% endfor %}
</ul>
{% if not overridable %}<p>{{ _("This dress is blocked or already given out for those dates. Pick another dress or other dates.") }}</p>{% endif %}
{% endif %}

<form method="post" action="/shop/walk-in">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  <label>{{ _("Dress code") }} <input name="code" value="{{ values.code }}" required maxlength="4" autocapitalize="characters"></label>
  <label>{{ _("Type") }} <select name="kind">
    <option value="walk_in" {% if values.kind == "walk_in" %}selected{% endif %}>{{ _("In the shop") }}</option>
    <option value="phone" {% if values.kind == "phone" %}selected{% endif %}>{{ _("By phone") }}</option>
  </select></label>
  <label>{{ _("Pickup") }} <input type="date" name="pickup_date" value="{{ values.pickup_date }}" required></label>
  <label>{{ _("Return") }} <input type="date" name="return_date" value="{{ values.return_date }}" required></label>
  <label>{{ _("Customer name") }} <input name="name" value="{{ values.name }}" required maxlength="120"></label>
  <label>{{ _("Phone") }} <input type="tel" name="phone" value="{{ values.phone }}" required placeholder="044 123 456"></label>
  <label>{{ _("Note") }} <input name="note" value="{{ values.note }}" maxlength="500"></label>
  <label class="inline"><input type="checkbox" name="picked_up_now" {% if values.picked_up_now %}checked{% endif %}> {{ _("The customer takes the dress now") }}</label>
  {% if overridable %}
  <label>{{ _("Why does this customer get the dress? The online booking will be flagged and we will find another dress for it.") }}
    <input name="override_reason" required maxlength="300"></label>
  <button>{{ _("Save anyway") }}</button>
  {% else %}
  <button>{{ _("Save") }}</button>
  {% endif %}
</form>
{% endblock %}
```

`src/twirl/templates/shop/calendar.html`:

```html
{% extends "shop/base.html" %}
{% block content %}
<h1>{{ _("Calendar") }}</h1>
<nav><a href="/shop/calendar?start={{ prev }}">← {{ _("Previous week") }}</a>
  · <a href="/shop/calendar?start={{ next }}">{{ _("Next week") }} →</a></nav>
<table class="calendar">
  <thead><tr><th>{{ _("Dress") }}</th>{% for day in days %}<th>{{ day|date }}</th>{% endfor %}</tr></thead>
  <tbody>
  {% for row in rows %}
    <tr>
      <th>{{ row.item.style.name }} · {{ row.item.size }} · {{ row.item.code }}</th>
      {% for cell in row.cells %}
        {% if cell %}
        <td data-kind="{{ cell.kind }}" data-status="{{ cell.status }}"><a href="/shop/bookings/{{ cell.id }}">{{ cell.ref }}</a></td>
        {% else %}<td></td>{% endif %}
      {% endfor %}
    </tr>
  {% else %}
    <tr><td colspan="8" class="muted">{{ _("No dresses yet.") }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

In `src/twirl/app.py`: delete `src/twirl/web/shop_home.py`, replace `shop_home` with `shop_bookings` in the `from twirl.web import ...` line and replace `shop_home.router` with `shop_bookings.router` in the router tuple.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: Today board, booking actions, walk-in entry and week calendar"
```

---

### Task 17: Public storefront — shop page, dress page, availability, request

**Files:**
- Create: `src/twirl/web/storefront.py`
- Create: `src/twirl/templates/storefront/shop.html`, `src/twirl/templates/storefront/style.html`, `src/twirl/templates/storefront/_availability.html`, `src/twirl/templates/storefront/confirmation.html`
- Modify: `src/twirl/app.py`
- Test: `tests/test_storefront.py`

**Interfaces:**
- Consumes: `create_request`, `RentalRequest`, `style_availability`, errors, `DATE_ERRORS`, `image_url`, `size_sort_key`, `get_storage`, `verify_csrf`, `form_data`, `validate_form`, `client_ip`, `app.state.request_limiter`.
- Produces: routes `GET /{slug}`, `GET /{slug}/r/{ref}`, `GET /{slug}/{code}`, `GET /{slug}/{code}/availability?event_date=YYYY-MM-DD` (HTML fragment), `POST /{slug}/{code}/request`. This router is registered last so fixed paths win.

- [ ] **Step 1: Write the failing tests**

`tests/test_storefront.py`:

```python
from datetime import timedelta

from sqlalchemy import func, select

from tests.factories import make_booking, make_item, make_shop, make_style
from tests.helpers import post
from twirl import clock
from twirl.booking.dates import derive_rental_dates
from twirl.booking.rules import rules_for_shop
from twirl.models import Booking

EVENT = clock.today() + timedelta(days=30)


def _dress(db, shop):
    style = make_style(db, shop, name="Red silk gown", price_cents=5500)
    return style, make_item(db, style, size="38"), make_item(db, style, size="40")


def _request_data(**over):
    data = {"event_date": EVENT.isoformat(), "size": "38", "name": "Arta",
            "phone": "044 123 456", "note": "Për maturë"}
    data.update(over)
    return data


def test_shop_page_lists_only_published_dresses(client, db, shop):
    _dress(db, shop)
    make_style(db, shop, name="Secret dress", published=False)
    response = client.get("/bella")
    assert response.status_code == 200
    assert "Red silk gown" in response.text
    assert "Secret dress" not in response.text


def test_draft_shop_is_hidden(client, db):
    make_shop(db, slug="draft-shop", status="draft")
    assert client.get("/draft-shop").status_code == 404


def test_style_page_has_sizes_and_share_tags(client, db, shop):
    style, _, _ = _dress(db, shop)
    response = client.get(f"/bella/{style.code}")
    assert response.status_code == 200
    assert 'property="og:title"' in response.text
    assert 'value="38"' in response.text and 'value="40"' in response.text


def test_availability_fragment_marks_taken_sizes(client, db, shop):
    style, item38, _ = _dress(db, shop)
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, item38, pickup=dates.pickup, return_=dates.return_)
    response = client.get(f"/bella/{style.code}/availability?event_date={EVENT.isoformat()}")
    assert response.status_code == 200
    assert '<li class="taken">38' in response.text
    assert '<li class="free">40' in response.text


def test_availability_for_too_soon_date_shows_error(client, db, shop):
    style, _, _ = _dress(db, shop)
    response = client.get(f"/bella/{style.code}/availability?event_date={clock.today().isoformat()}")
    assert 'class="error"' in response.text


def test_request_creates_pending_booking_and_confirmation(client, db, shop, owner):
    style, _, _ = _dress(db, shop)
    response = post(client, f"/bella/{style.code}/request", _request_data())
    assert response.status_code == 303
    booking = db.scalars(select(Booking).where(Booking.shop_id == shop.id)).one()
    assert response.headers["location"] == f"/bella/r/{booking.ref}"
    assert (booking.status, booking.customer_note) == ("pending_shop", "Për maturë")
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert booking.ref in page.text


def test_confirmation_links_to_shop_whatsapp(client, db, shop):
    shop.whatsapp = "+38344111222"
    style, _, _ = _dress(db, shop)
    location = post(client, f"/bella/{style.code}/request", _request_data()).headers["location"]
    assert "https://wa.me/38344111222?text=" in client.get(location).text


def test_honeypot_silently_drops_bots(client, db, shop):
    style, _, _ = _dress(db, shop)
    response = post(client, f"/bella/{style.code}/request", _request_data(website="http://spam.example"))
    assert (response.status_code, response.headers["location"]) == (303, "/bella")
    assert db.scalar(select(func.count()).select_from(Booking)) == 0


def test_unavailable_size_is_409(client, db, shop):
    style, _, _ = _dress(db, shop)
    assert post(client, f"/bella/{style.code}/request", _request_data(size="42")).status_code == 409


def test_bad_phone_is_400(client, db, shop):
    style, _, _ = _dress(db, shop)
    assert post(client, f"/bella/{style.code}/request", _request_data(phone="123")).status_code == 400


def test_requests_are_rate_limited(client, db, shop):
    style, _, _ = _dress(db, shop)
    statuses = [post(client, f"/bella/{style.code}/request", _request_data(size="42")).status_code
                for _ in range(6)]
    assert statuses == [409, 409, 409, 409, 409, 429]


def test_fixed_paths_are_not_shadowed(client):
    assert client.get("/login").status_code == 200
    assert client.get("/healthz").status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storefront.py -v`
Expected: FAIL with 404 on `/bella`.

- [ ] **Step 3: Implement the storefront routes**

`src/twirl/web/storefront.py`:

```python
from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from twirl import clock
from twirl.auth.csrf import verify_csrf
from twirl.booking.availability import style_availability
from twirl.booking.errors import InvalidDates, NoAvailability, ShopNotBookable
from twirl.booking.requests import RentalRequest, create_request
from twirl.catalog import image_url, size_sort_key
from twirl.db import get_db
from twirl.i18n import N_
from twirl.models import Booking, BookingKind, Item, ItemStatus, Shop, ShopStatus, Style
from twirl.phones import InvalidPhone
from twirl.ratelimit import client_ip
from twirl.storage import Storage, get_storage
from twirl.web.forms import form_data, validate_form
from twirl.web.messages import DATE_ERRORS, GENERIC_DATE_ERROR
from twirl.web.templating import render

router = APIRouter()

RENTER_STATUS = {
    "pending_shop": N_("The shop will confirm your request within 24 hours."),
    "confirmed": N_("The shop has confirmed your booking."),
}
CLOSED_STATUS = N_("This request is closed. Contact the shop for details.")


class RequestForm(BaseModel):
    event_date: date
    size: str = Field(min_length=1, max_length=8)
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=30)
    note: str = Field(default="", max_length=500)


def _shop(db: Session, slug: str) -> Shop:
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.status == ShopStatus.PUBLISHED.value))
    if shop is None:
        raise HTTPException(status_code=404)
    return shop


def _style(db: Session, shop: Shop, code: str) -> Style:
    style = db.scalar(
        select(Style).where(
            Style.shop_id == shop.id, Style.code == code, Style.published.is_(True),
            Style.deleted_at.is_(None),
        )
    )
    if style is None:
        raise HTTPException(status_code=404)
    return style


def _style_context(request: Request, db: Session, storage: Storage, shop: Shop, style: Style) -> dict:
    sizes = sorted(
        set(db.scalars(select(Item.size).where(Item.style_id == style.id,
                                               Item.status == ItemStatus.ACTIVE.value))),
        key=size_sort_key,
    )
    images = [
        {"thumb": image_url(storage, i, "thumb"), "detail": image_url(storage, i, "detail")}
        for i in style.images
    ]
    base_url = request.app.state.settings.base_url
    return {
        "shop": shop, "style": style, "sizes": sizes, "images": images,
        "og_image": f"{base_url}{images[0]['detail']}" if images else None,
        "min_date": (clock.today() + timedelta(days=1)).isoformat(),
    }


@router.get("/{slug}", response_class=HTMLResponse)
def shop_page(request: Request, slug: str, db: Session = Depends(get_db),
              storage: Storage = Depends(get_storage)):
    shop = _shop(db, slug)
    styles = db.scalars(
        select(Style)
        .where(Style.shop_id == shop.id, Style.published.is_(True), Style.deleted_at.is_(None))
        .order_by(Style.created_at.desc())
    ).all()
    cards = [{"style": s, "thumb": image_url(storage, s.images[0]) if s.images else None} for s in styles]
    return render(request, "storefront/shop.html", {"shop": shop, "cards": cards})


@router.get("/{slug}/r/{ref}", response_class=HTMLResponse)
def confirmation(request: Request, slug: str, ref: str, db: Session = Depends(get_db)):
    shop = _shop(db, slug)
    booking = db.scalar(
        select(Booking).where(Booking.shop_id == shop.id, Booking.ref == ref,
                              Booking.kind == BookingKind.ONLINE.value)
    )
    if booking is None:
        raise HTTPException(status_code=404)
    text = quote(f"Përshëndetje! Kam një kërkesë në Twirl me kodin {booking.ref}.")
    return render(
        request, "storefront/confirmation.html",
        {
            "shop": shop, "booking": booking,
            "status_text": RENTER_STATUS.get(booking.status, CLOSED_STATUS),
            "whatsapp_url": f"https://wa.me/{shop.whatsapp.lstrip('+')}?text={text}" if shop.whatsapp else None,
            "viber_url": f"viber://chat?number={quote(shop.viber)}" if shop.viber else None,
        },
    )


@router.get("/{slug}/{code}", response_class=HTMLResponse)
def style_page(request: Request, slug: str, code: str, db: Session = Depends(get_db),
               storage: Storage = Depends(get_storage)):
    shop = _shop(db, slug)
    style = _style(db, shop, code)
    context = _style_context(request, db, storage, shop, style)
    return render(request, "storefront/style.html", {**context, "values": {}, "error": None})


@router.get("/{slug}/{code}/availability", response_class=HTMLResponse)
def availability(request: Request, slug: str, code: str,
                 event_date: date | None = Query(None), db: Session = Depends(get_db)):
    shop = _shop(db, slug)
    style = _style(db, shop, code)
    context = {"availability": None, "error": None}
    if event_date is not None:
        try:
            context["availability"] = style_availability(db, style, event_date, today=clock.today())
        except InvalidDates as exc:
            context["error"] = DATE_ERRORS.get(exc.code, GENERIC_DATE_ERROR)
    return render(request, "storefront/_availability.html", context)


@router.post("/{slug}/{code}/request", dependencies=[Depends(verify_csrf)])
def request_dress(request: Request, slug: str, code: str, form: FormData = Depends(form_data),
                  db: Session = Depends(get_db), storage: Storage = Depends(get_storage)):
    shop = _shop(db, slug)
    style = _style(db, shop, code)
    settings = request.app.state.settings
    values = {key: str(form.get(key) or "") for key in ("event_date", "size", "name", "phone", "note")}

    def page(error: str, status_code: int = 400):
        context = _style_context(request, db, storage, shop, style)
        return render(request, "storefront/style.html", {**context, "values": values, "error": error},
                      status_code=status_code)

    if form.get("website"):
        return RedirectResponse(f"/{shop.slug}", status_code=303)
    if not request.app.state.request_limiter.allow(
        client_ip(request, trust_cf=settings.trust_cf_connecting_ip)
    ):
        return page(N_("Too many requests from your connection. Try again later."), 429)
    parsed, _ = validate_form(RequestForm, form)
    if parsed is None:
        return page(N_("Please fill in your event date, size, name and phone."))
    try:
        booking = create_request(
            db,
            RentalRequest(style_id=style.id, size=parsed.size, event_date=parsed.event_date,
                          name=parsed.name, phone=parsed.phone, note=parsed.note),
            today=clock.today(),
        )
    except InvalidPhone:
        db.rollback()
        return page(N_("That phone number does not look right."))
    except InvalidDates as exc:
        db.rollback()
        return page(DATE_ERRORS.get(exc.code, GENERIC_DATE_ERROR))
    except NoAvailability:
        db.rollback()
        return page(N_("Sorry, that size is not free for your date. Try another size or date."), 409)
    except ShopNotBookable as exc:
        db.rollback()
        raise HTTPException(status_code=404) from exc
    db.commit()
    return RedirectResponse(f"/{shop.slug}/r/{booking.ref}", status_code=303)
```

- [ ] **Step 4: Add the templates**

`src/twirl/templates/storefront/shop.html`:

```html
{% extends "base.html" %}
{% block title %}{{ shop.name }} · Twirl{% endblock %}
{% block head %}
<meta property="og:title" content="{{ shop.name }}">
<meta property="og:description" content="{{ _('Dresses to rent in') }} {{ shop.city }}">
{% endblock %}
{% block content %}
<h1>{{ shop.name }}</h1>
<p class="muted">{% if shop.address %}{{ shop.address }}, {% endif %}{{ shop.city }}</p>
<ul class="cards">
  {% for card in cards %}
  <li><a href="/{{ shop.slug }}/{{ card.style.code }}">
    {% if card.thumb %}<img src="{{ card.thumb }}" alt="{{ card.style.name }}" width="200" height="267" loading="lazy">{% endif %}
    <strong>{{ card.style.name }}</strong> · {{ card.style.price_cents|money(locale) }}</a></li>
  {% else %}
  <li class="muted">{{ _("No dresses online yet.") }}</li>
  {% endfor %}
</ul>
{% endblock %}
```

`src/twirl/templates/storefront/style.html`:

```html
{% extends "base.html" %}
{% block title %}{{ style.name }} · {{ shop.name }}{% endblock %}
{% block head %}
<meta property="og:title" content="{{ style.name }} · {{ shop.name }}">
<meta property="og:description" content="{{ style.price_cents|money(locale) }} · {{ shop.city }}">
{% if og_image %}<meta property="og:image" content="{{ og_image }}">{% endif %}
{% endblock %}
{% block content %}
<p><a href="/{{ shop.slug }}">← {{ shop.name }}</a></p>
<h1>{{ style.name }}</h1>
<p><strong>{{ style.price_cents|money(locale) }}</strong> {{ _("per rental, paid in the shop") }}</p>
<div class="photos">
  {% for image in images %}<img src="{{ image.detail }}" alt="{{ style.name }}" width="300" height="400" loading="{{ 'eager' if loop.first else 'lazy' }}">{% endfor %}
</div>
{% if style.description %}<p>{{ style.description }}</p>{% endif %}
<ul class="fit">
  {% if style.length %}<li>{{ _("Length") }}: {{ style.length }}</li>{% endif %}
  {% if style.stretch %}<li>{{ _("Stretch fabric") }}</li>{% endif %}
  {% if style.adjustable_back %}<li>{{ _("Adjustable back") }}</li>{% endif %}
</ul>

{% if error %}<p class="error" role="alert">{{ _(error) }}</p>{% endif %}
<form method="post" action="/{{ shop.slug }}/{{ style.code }}/request" class="request">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  <label>{{ _("Event date") }}
    <input type="date" name="event_date" min="{{ min_date }}" value="{{ values.event_date or '' }}" required
      hx-get="/{{ shop.slug }}/{{ style.code }}/availability" hx-trigger="change" hx-target="#availability"
      hx-include="this"></label>
  <div id="availability" aria-live="polite"></div>
  <label>{{ _("Size") }}
    <select name="size" required>
      {% for size in sizes %}<option value="{{ size }}" {% if values.size == size %}selected{% endif %}>{{ size }}</option>{% endfor %}
    </select></label>
  <label>{{ _("Your name") }} <input name="name" value="{{ values.name or '' }}" required maxlength="120"></label>
  <label>{{ _("Phone") }} <input type="tel" name="phone" value="{{ values.phone or '' }}" required placeholder="044 123 456"></label>
  <label>{{ _("Note for the shop (optional)") }} <textarea name="note" maxlength="500">{{ values.note or '' }}</textarea></label>
  <div class="hp" aria-hidden="true"><label>Website <input name="website" tabindex="-1" autocomplete="off"></label></div>
  <button>{{ _("Request this dress") }}</button>
  <p class="muted">{{ _("No payment now. The shop confirms your request, then you pick up and pay in the shop.") }}</p>
</form>

<h2>{{ shop.name }}</h2>
<p>{% if shop.address %}{{ shop.address }}, {% endif %}{{ shop.city }}</p>
{% if shop.terms_text %}<h3>{{ _("Shop terms") }}</h3><p>{{ shop.terms_text }}</p>{% endif %}
{% endblock %}
```

`src/twirl/templates/storefront/_availability.html`:

```html
{% if error %}
<p class="error">{{ _(error) }}</p>
{% elif availability %}
<p>{{ _("Pickup") }} {{ availability.dates.pickup|date }} · {{ _("Return") }} {{ availability.dates.return_|date }}</p>
<ul class="sizes">
  {% for size, free in availability.sizes.items() %}<li class="{{ 'free' if free else 'taken' }}">{{ size }}: {{ _("free") if free else _("taken") }}</li>{% endfor %}
</ul>
{% else %}
<p class="muted">{{ _("Pick your event date to see which sizes are free.") }}</p>
{% endif %}
```

`src/twirl/templates/storefront/confirmation.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>{{ _("Request sent") }}</h1>
<p>{{ _("Your code") }}: <strong>{{ booking.ref }}</strong></p>
<p>{{ _(status_text) }}</p>
<dl>
  <dt>{{ _("Dress") }}</dt><dd>{{ booking.style.name }} · {{ _("size") }} {{ booking.item.size }}</dd>
  <dt>{{ _("Event") }}</dt><dd>{{ booking.event_date|date }}</dd>
  <dt>{{ _("Pickup") }}</dt><dd>{{ booking.pickup_date|date }}</dd>
  <dt>{{ _("Return") }}</dt><dd>{{ booking.return_date|date }}</dd>
  <dt>{{ _("Price, paid in the shop") }}</dt><dd>{{ booking.price_cents|money(locale) }}</dd>
  <dt>{{ _("Shop") }}</dt><dd>{{ shop.name }}{% if shop.address %}, {{ shop.address }}{% endif %}, {{ shop.city }}</dd>
</dl>
{% if shop.terms_text %}<h2>{{ _("Shop terms") }}</h2><p>{{ shop.terms_text }}</p>{% endif %}
{% if whatsapp_url %}<p><a href="{{ whatsapp_url }}">{{ _("Message the shop on WhatsApp") }}</a></p>{% endif %}
{% if viber_url %}<p><a href="{{ viber_url }}">{{ _("Message the shop on Viber") }}</a></p>{% endif %}
{% endblock %}
```

In `src/twirl/app.py`, add `storefront` to the `from twirl.web import ...` line and add this as the last line before `return app` (it must stay last, because `/{slug}` matches any single path segment):

```python
    app.include_router(storefront.router)
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: public storefront with live size availability and request-to-book"
```

---

### Task 18: Admin console and command-line setup

**Files:**
- Create: `src/twirl/web/admin.py`, `src/twirl/cli.py`
- Modify: `src/twirl/app.py`
- Test: `tests/test_admin.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: all models, `hash_password`, `verify_password`, `is_valid_slug`, `Database`, `get_settings`.
- Produces: `mount_admin(app, db, settings) -> Admin` at `/admin` (read-only bookings, events and notifications; editable shops, users, styles, items); `cmd_create_admin(session, *, email, name, password) -> User`, `cmd_create_shop(session, *, slug, name, city, owner_email, owner_name, owner_password, staff_email=None, staff_password=None) -> Shop`, `cmd_publish_shop(session, *, slug) -> Shop`, `main(argv=None) -> int` behind the `twirl` console script.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
import pytest
from sqlalchemy import select

from twirl.auth.passwords import verify_password
from twirl.cli import cmd_create_admin, cmd_create_shop, cmd_publish_shop
from twirl.models import ShopUser, User


def _shop(db, **over):
    kwargs = dict(slug="bella-2", name="Bella", city="Ferizaj", owner_email="Owner@Bella.test",
                  owner_name="Drita", owner_password="pw-123456")
    kwargs.update(over)
    return cmd_create_shop(db, **kwargs)


def test_create_shop_with_owner_and_staff(db):
    shop = _shop(db, staff_email="staff@bella.test", staff_password="pw-654321")
    assert shop.status == "draft"
    roles = sorted(db.scalars(select(ShopUser.role).where(ShopUser.shop_id == shop.id)))
    assert roles == ["owner", "staff"]
    owner = db.scalar(select(User).where(User.email == "owner@bella.test"))
    assert verify_password(owner.password_hash, "pw-123456")


def test_reserved_slug_is_rejected(db):
    with pytest.raises(ValueError):
        _shop(db, slug="admin")


def test_short_password_is_rejected(db):
    with pytest.raises(ValueError):
        _shop(db, owner_password="short")


def test_publish_shop(db):
    _shop(db)
    assert cmd_publish_shop(db, slug="bella-2").status == "published"


def test_create_admin(db):
    admin = cmd_create_admin(db, email="Me@Twirl.test", name="Me", password="pw-123456")
    assert (admin.kind, admin.email) == ("admin", "me@twirl.test")
```

`tests/test_admin.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from twirl.app import create_app
from twirl.cli import cmd_create_admin


def test_admin_requires_login(client):
    response = client.get("/admin/", follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "/admin/login" in response.headers["location"]


def test_admin_login_and_lists(committed, settings):
    with sessionmaker(committed)() as session:
        cmd_create_admin(session, email="me@twirl.test", name="Me", password="pw-123456")
        session.commit()
    with TestClient(create_app(settings)) as admin_client:
        bad = admin_client.post("/admin/login", data={"username": "me@twirl.test", "password": "wrong"},
                                follow_redirects=False)
        assert bad.status_code == 400
        good = admin_client.post("/admin/login", data={"username": "me@twirl.test", "password": "pw-123456"},
                                 follow_redirects=False)
        assert good.status_code in (302, 303)
        for model in ("shop", "user", "style", "item", "booking", "booking-event", "notification"):
            assert admin_client.get(f"/admin/{model}/list").status_code == 200, model
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py tests/test_admin.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'twirl.cli'`.

- [ ] **Step 3: Implement the CLI**

`src/twirl/cli.py`:

```python
import argparse
from getpass import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl.auth.passwords import hash_password
from twirl.config import get_settings
from twirl.db import Database
from twirl.models import Shop, ShopRole, ShopStatus, ShopUser, User, UserKind
from twirl.slugs import is_valid_slug

MIN_PASSWORD_LENGTH = 8


def _login_user(session: Session, *, kind: UserKind, email: str, name: str, password: str) -> User:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError("password must be at least 8 characters")
    user = User(kind=kind.value, name=name.strip(), email=email.strip().lower(),
                password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def cmd_create_admin(session: Session, *, email: str, name: str, password: str) -> User:
    return _login_user(session, kind=UserKind.ADMIN, email=email, name=name, password=password)


def cmd_create_shop(
    session: Session, *, slug: str, name: str, city: str, owner_email: str, owner_name: str,
    owner_password: str, staff_email: str | None = None, staff_password: str | None = None,
) -> Shop:
    if not is_valid_slug(slug):
        raise ValueError(f"invalid or reserved slug: {slug}")
    shop = Shop(slug=slug, name=name.strip(), city=city.strip(), status=ShopStatus.DRAFT.value)
    session.add(shop)
    session.flush()
    owner = _login_user(session, kind=UserKind.SHOP, email=owner_email, name=owner_name,
                        password=owner_password)
    session.add(ShopUser(shop_id=shop.id, user_id=owner.id, role=ShopRole.OWNER.value))
    if staff_email:
        staff = _login_user(session, kind=UserKind.SHOP, email=staff_email, name=f"{name} staff",
                            password=staff_password or "")
        session.add(ShopUser(shop_id=shop.id, user_id=staff.id, role=ShopRole.STAFF.value))
    session.flush()
    return shop


def cmd_publish_shop(session: Session, *, slug: str) -> Shop:
    shop = session.scalars(select(Shop).where(Shop.slug == slug)).one()
    shop.status = ShopStatus.PUBLISHED.value
    session.flush()
    return shop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="twirl")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    shop = sub.add_parser("create-shop")
    for flag in ("--slug", "--name", "--city", "--owner-email", "--owner-name"):
        shop.add_argument(flag, required=True)
    shop.add_argument("--staff-email")
    publish = sub.add_parser("publish-shop")
    publish.add_argument("--slug", required=True)
    args = parser.parse_args(argv)

    db = Database(get_settings().database_url)
    with db.sessionmaker() as session:
        if args.command == "create-admin":
            cmd_create_admin(session, email=args.email, name=args.name, password=getpass("Admin password: "))
        elif args.command == "create-shop":
            cmd_create_shop(
                session, slug=args.slug, name=args.name, city=args.city,
                owner_email=args.owner_email, owner_name=args.owner_name,
                owner_password=getpass("Owner password: "),
                staff_email=args.staff_email,
                staff_password=getpass("Staff password: ") if args.staff_email else None,
            )
        else:
            cmd_publish_shop(session, slug=args.slug)
        session.commit()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Implement the admin console**

`src/twirl/web/admin.py`:

```python
from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from twirl.auth.passwords import verify_password
from twirl.config import Settings
from twirl.db import Database
from twirl.models import (
    Booking, BookingEvent, Item, Notification, Shop, Style, User, UserKind,
)

ADMIN_SESSION_KEY = "admin_uid"


class AdminAuth(AuthenticationBackend):
    def __init__(self, secret_key: str, db: Database) -> None:
        super().__init__(secret_key=secret_key)
        self._db = db

    def _check(self, email: str, password: str) -> int | None:
        with self._db.sessionmaker() as session:
            user = session.scalar(
                select(User).where(User.email == email, User.kind == UserKind.ADMIN.value)
            )
            if (
                user is not None
                and user.password_hash
                and user.blocked_at is None
                and verify_password(user.password_hash, password)
            ):
                return user.id
        return None

    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = str(form.get("username", "")).strip().lower()
        password = str(form.get("password", ""))
        user_id = await run_in_threadpool(self._check, email, password)
        if user_id is None:
            return False
        request.session.update({ADMIN_SESSION_KEY: user_id})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return ADMIN_SESSION_KEY in request.session


class ShopAdmin(ModelView, model=Shop):
    column_list = [Shop.id, Shop.slug, Shop.name, Shop.city, Shop.status, Shop.booking_mode]
    column_searchable_list = [Shop.slug, Shop.name]
    form_columns = [
        Shop.name, Shop.city, Shop.address, Shop.phone, Shop.whatsapp, Shop.viber, Shop.instagram,
        Shop.status, Shop.booking_mode, Shop.pickup_lead_days, Shop.return_after_days,
        Shop.prep_days, Shop.cleaning_days, Shop.max_rental_days,
    ]
    can_delete = False


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.kind, User.name, User.email, User.phone, User.blocked_at]
    column_searchable_list = [User.email, User.phone, User.name]
    form_columns = [User.name, User.email, User.phone, User.locale, User.blocked_at]
    can_create = False
    can_delete = False


class StyleAdmin(ModelView, model=Style):
    column_list = [Style.id, Style.shop_id, Style.code, Style.name, Style.price_cents, Style.published]
    column_searchable_list = [Style.name, Style.code]
    form_columns = [Style.name, Style.description, Style.price_cents, Style.published]
    can_create = False
    can_delete = False


class ItemAdmin(ModelView, model=Item):
    column_list = [Item.id, Item.shop_id, Item.style_id, Item.code, Item.size, Item.status]
    column_searchable_list = [Item.code]
    form_columns = [Item.size, Item.status, Item.notes]
    can_create = False
    can_delete = False


class BookingAdmin(ModelView, model=Booking):
    column_list = [
        Booking.id, Booking.ref, Booking.shop_id, Booking.item_id, Booking.kind, Booking.status,
        Booking.pickup_date, Booking.return_date, Booking.created_at,
    ]
    column_searchable_list = [Booking.ref]
    column_sortable_list = [Booking.created_at, Booking.pickup_date]
    column_default_sort = [(Booking.created_at, True)]
    can_create = False
    can_edit = False
    can_delete = False


class BookingEventAdmin(ModelView, model=BookingEvent):
    column_list = [
        BookingEvent.id, BookingEvent.booking_id, BookingEvent.from_status, BookingEvent.to_status,
        BookingEvent.actor_kind, BookingEvent.reason, BookingEvent.created_at,
    ]
    column_default_sort = [(BookingEvent.id, True)]
    can_create = False
    can_edit = False
    can_delete = False


class NotificationAdmin(ModelView, model=Notification):
    column_list = [
        Notification.id, Notification.channel, Notification.recipient, Notification.template,
        Notification.status, Notification.attempts, Notification.last_error, Notification.created_at,
    ]
    column_default_sort = [(Notification.id, True)]
    can_create = False
    can_edit = False
    can_delete = False


def mount_admin(app: FastAPI, db: Database, settings: Settings) -> Admin:
    admin = Admin(
        app, engine=db.engine, session_maker=db.sessionmaker, base_url="/admin", title="Twirl admin",
        authentication_backend=AdminAuth(settings.secret_key, db),
    )
    for view in (ShopAdmin, UserAdmin, StyleAdmin, ItemAdmin, BookingAdmin, BookingEventAdmin,
                 NotificationAdmin):
        admin.add_view(view)
    return admin
```

In `src/twirl/app.py`:
- add `from twirl.web.admin import mount_admin` to the imports;
- immediately before `app.include_router(storefront.router)`, add:

```python
    mount_admin(app, app.state.db, settings)
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass. If `test_admin_login_and_lists` fails on a model URL, print `[v.identity for v in admin.views]` and use sqladmin's actual identities in the test; the default identity is the model class name in kebab case.

- [ ] **Step 6: Try the whole slice by hand**

```bash
uv run alembic upgrade head
uv run twirl create-admin --email you@example.com --name "Elton"
uv run twirl create-shop --slug bella --name "Bella" --city Ferizaj --owner-email owner@example.com --owner-name "Owner"
uv run twirl publish-shop --slug bella
uv run uvicorn twirl.app:create_app --factory --reload
```

Log in at `http://localhost:8000/login`, add a dress with a photo and two sizes, open `http://localhost:8000/bella`, request the dress, accept it from Today, and enter a conflicting walk-in to see the override flow. Check `/admin/` shows the booking and its events.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: admin console and CLI for shop onboarding"
```

---

### Task 19: Albanian translation pass

**Files:**
- Create: `src/twirl/locale/messages.pot`
- Modify: `src/twirl/locale/sq/LC_MESSAGES/messages.po` (+ recompiled `.mo`)
- Test: `tests/test_translations.py`

**Interfaces:**
- Consumes: every `_()` in templates and every `N_()` in Python from Tasks 11–17.
- Produces: a complete Albanian catalog and a CI check that fails on any untranslated, fuzzy or unextracted string (spec NFR-07).

- [ ] **Step 1: Write the failing tests**

`tests/test_translations.py`:

```python
from pathlib import Path

from babel.messages.extract import extract_from_dir
from babel.messages.pofile import read_po

ROOT = Path(__file__).resolve().parents[1]
PO_FILE = ROOT / "src/twirl/locale/sq/LC_MESSAGES/messages.po"
METHOD_MAP = [("**.py", "python"), ("**/templates/**.html", "jinja2")]
OPTIONS = {"**/templates/**.html": {"extensions": "jinja2.ext.i18n"}}


def _catalog():
    with PO_FILE.open("rb") as handle:
        return read_po(handle)


def test_every_albanian_string_is_translated():
    catalog = _catalog()
    missing = [m.id for m in catalog if m.id and not m.string]
    fuzzy = [m.id for m in catalog if m.id and m.fuzzy]
    assert not missing, missing
    assert not fuzzy, fuzzy


def test_catalog_contains_every_source_string():
    catalog = _catalog()
    source = {
        message
        for _, _, message, _, _ in extract_from_dir(
            str(ROOT / "src/twirl"), METHOD_MAP, OPTIONS, keywords={"_": None, "N_": None}
        )
        if isinstance(message, str)
    }
    missing = sorted(source - {m.id for m in catalog if m.id})
    assert not missing, missing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_translations.py -v`
Expected: FAIL, listing every English string added since Task 11.

- [ ] **Step 3: Extract and update the catalog**

```bash
uv run pybabel extract -F babel.cfg -k N_ -o src/twirl/locale/messages.pot .
uv run pybabel update -i src/twirl/locale/messages.pot -d src/twirl/locale -l sq --no-fuzzy-matching
```

- [ ] **Step 4: Translate every empty `msgstr` in `src/twirl/locale/sq/LC_MESSAGES/messages.po`**

Rules:
- Address the reader with the polite plural ("ju"): "Zgjidhni", "Shkruani", not "Zgjidh".
- Use the market's own words from spec Appendix B: size = **masa**, reserve = **rezervo**, wedding = **dasmë**, engagement = **fejesë**, henna night = **nata e kanës**, matura = **maturë**, dress for rent = **fustan me qira**.
- Fixed terms: booking = **rezervim**, request = **kërkesë**, pickup = **marrja**, return = **kthimi**, walk-in = **klient në dyqan**, shop = **dyqan**, code = **kodi**, at risk = **në rrezik**, block (a dress) = **blloko**.
- Keep `€`, dress codes and booking codes untouched.
- Leave nothing fuzzy; delete any `#, fuzzy` line after checking the text.

The founder is a native speaker and reviews this file before the pilot; mark nothing as final in the commit message.

- [ ] **Step 5: Compile and run tests**

```bash
uv run pybabel compile -d src/twirl/locale -D messages
uv run pytest -v
```

Expected: all pass, including both translation tests.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: Albanian UI translation (draft for native review)"
```

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| ENG-01 no double booking, 50-way concurrency test | 4, 8 |
| ENG-02 blocked ranges from shop rules | 5, 8, 9 |
| ENG-04 system picks the item | 8 |
| ENG-06 walk-in override with reason, alert | 9, 16 |
| ENG-07 request SLA auto-cancel (24 h wall clock only) | 10 |
| ENG-08 blocks and closure days | 9, 13, 15 |
| ENG-11 booking timeline | 6, 16 |
| ENG-12 swap to another item | 9, 16 |
| SHP-01 shop profile and rules | 13 |
| SHP-02 add a dress from the phone | 14, 15 |
| SHP-04 item code, QR, status, condition history | 3, 9, 15 |
| SHP-05 Today list and week calendar | 16 |
| SHP-06 walk-in in a few inputs | 16 |
| SHP-07 accept or decline requests | 16 |
| SHP-08 lifecycle buttons | 16 |
| SHP-09 swap | 9, 16 |
| SHP-10 block a dress, close the shop | 13, 15 |
| SHP-11 shared staff login with limits | 12, 13, 15 |
| SHP-13 notified of new requests (email + Telegram) | 7, 10 |
| RNT-01 storefront without account | 17 |
| RNT-04 style page | 17 |
| RNT-07 request a dress for a date (no hold, no fee in this slice) | 8, 17 |
| RNT-14 WhatsApp and Viber links | 17 |
| RNT-16 Albanian and English | 11, 19 |
| RNT-18 share tags | 17 |
| NFR-02 image pipeline | 14 |
| NFR-07 no untranslated strings (CI check) | 19 |
| §8.2 CSRF, argon2, rate limits, upload re-encoding | 11, 12, 14, 17 |
| ADM-01, ADM-03 admin console for shops and bookings | 18 |

Not covered here on purpose: everything under "Out of scope" above, plus SLA nudges at 1 h and 2 h (ENG-07), ENG-10 instant unlock rules, ENG-13 agenda import, SHP-03 catalog import, SHP-12 statements, SHP-15 customer list screen, SHP-22 agreement acceptance.
