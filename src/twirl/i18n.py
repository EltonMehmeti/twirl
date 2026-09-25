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
