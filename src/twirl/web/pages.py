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
