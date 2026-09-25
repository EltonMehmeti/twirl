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
