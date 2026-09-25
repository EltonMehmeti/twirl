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
