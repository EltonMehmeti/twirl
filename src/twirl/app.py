import base64
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from twirl.auth.deps import LoginRequired
from twirl.config import Settings, get_settings
from twirl.db import Database
from twirl.notify.senders import LogSender
from twirl.ratelimit import RateLimiter
from twirl.scheduler import start_scheduler
from twirl.storage import LocalStorage, build_storage
from twirl.web import (
    auth,
    health,
    internal,
    media,
    onboarding,
    pages,
    shop_bookings,
    shop_catalog,
    shop_settings,
    storefront,
)
from twirl.web.admin import mount_admin
from twirl.web.templating import render

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


OPEN_PATHS = ("/healthz", "/internal/")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Puts the whole site behind one shared login (staging). Health checks and cron stay open."""

    def __init__(self, app, credentials: str) -> None:
        super().__init__(app)
        self.expected = "Basic " + base64.b64encode(credentials.encode()).decode()

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(OPEN_PATHS):
            return await call_next(request)
        sent = request.headers.get("authorization", "")
        if not hmac.compare_digest(sent.encode(), self.expected.encode()):
            return PlainTextResponse(
                "Login required",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Vesha staging"'},
            )
        return await call_next(request)


async def _http_error_page(request: Request, exc: StarletteHTTPException):
    wants_html = "text/html" in request.headers.get(
        "accept", ""
    ) or not request.url.path.startswith(("/internal", "/static", "/media"))
    if exc.status_code in (403, 404) and wants_html:
        return render(
            request, "error.html", {"status": exc.status_code}, status_code=exc.status_code
        )
    return await http_exception_handler(request, exc)


async def _login_redirect(request: Request, exc: LoginRequired) -> RedirectResponse:
    return RedirectResponse(f"/login?next={quote(exc.next_path)}", status_code=303)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Twirl", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.storage = build_storage(settings)
    app.state.login_limiter = RateLimiter(10, 15 * 60)
    app.state.sms_sender = LogSender("sms")  # replaced once an SMS provider is chosen
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
    if isinstance(app.state.storage, LocalStorage):
        app.mount("/media", StaticFiles(directory=settings.media_root), name="media")
    else:
        app.include_router(media.router)
    if settings.basic_auth:
        app.add_middleware(BasicAuthMiddleware, credentials=settings.basic_auth)
    app.add_exception_handler(StarletteHTTPException, _http_error_page)
    for router in (
        health.router,
        internal.router,
        pages.router,
        auth.router,
        shop_bookings.router,
        shop_catalog.router,
        shop_settings.router,
    ):
        app.include_router(router)
    app.include_router(onboarding.router)
    mount_admin(app, app.state.db, settings)
    app.include_router(storefront.router)  # last: /{slug} matches any single segment
    return app
