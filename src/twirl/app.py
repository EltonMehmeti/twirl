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
