from contextvars import ContextVar
from datetime import date

from babel.support import NullTranslations
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse

from twirl.auth.csrf import get_csrf_token
from twirl.i18n import get_translations, pick_locale

_NULL_TRANSLATIONS = NullTranslations()
_current: ContextVar[NullTranslations | None] = ContextVar("twirl_translations", default=None)


def _gettext(message: str) -> str:
    return (_current.get() or _NULL_TRANSLATIONS).gettext(message)


def _ngettext(singular: str, plural: str, n: int) -> str:
    return (_current.get() or _NULL_TRANSLATIONS).ngettext(singular, plural, n)


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
