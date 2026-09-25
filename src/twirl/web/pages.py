from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from twirl import clock
from twirl.catalog import image_url
from twirl.db import get_db
from twirl.i18n import LOCALE_COOKIE, N_, SUPPORTED_LOCALES
from twirl.onboarding import CUSTOM_SIZE
from twirl.search import SORTS, Filters, city_options, search, shop_cards, size_options
from twirl.storage import Storage, get_storage
from twirl.web.onboarding import CATEGORY_LABELS
from twirl.web.templating import render

router = APIRouter()

PRICE_CAPS = (30, 50, 80, 120)
SORT_LABELS = [
    ("newest", N_("Newest")),
    ("price_asc", N_("Price: low to high")),
    ("price_desc", N_("Price: high to low")),
]
PAST_DATE = N_("Pick a date from tomorrow on.")


def safe_next(target: str | None, default: str = "/") -> str:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return default


def _parse_date(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _parse_int(raw: str | None) -> int | None:
    return int(raw) if raw and raw.isdigit() else None


def _query(filters: Filters, **changes) -> str:
    """The search URL with some filters changed, for links such as "any size"."""
    values = {
        "date": filters.event_date.isoformat() if filters.event_date else "",
        "size": filters.size or "",
        "city": filters.city or "",
        "category": filters.category or "",
        "max": str(filters.max_price_cents // 100) if filters.max_price_cents else "",
        "sort": "" if filters.sort == "newest" else filters.sort,
    }
    values.update({key: str(value) for key, value in changes.items()})
    query = urlencode({key: value for key, value in values.items() if value})
    return f"/?{query}" if query else "/"


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    date_: str | None = Query(None, alias="date"),
    size: str | None = None,
    city: str | None = None,
    category: str | None = None,
    max_: str | None = Query(None, alias="max"),
    sort: str | None = None,
    page: str | None = None,
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    today = clock.today()
    sizes = size_options(db)
    cities = city_options(db)
    event_date = _parse_date(date_)
    date_error = None
    if event_date is not None and event_date <= today:
        event_date, date_error = None, PAST_DATE
    max_euros = _parse_int(max_)
    filters = Filters(
        event_date=event_date,
        size=size if size in sizes else None,
        city=city if city in cities else None,
        category=category if category in dict(CATEGORY_LABELS) else None,
        max_price_cents=max_euros * 100 if max_euros else None,
        sort=sort if sort in SORTS else "newest",
        page=_parse_int(page) or 1,
    )
    results = search(db, filters, today=today)
    detail_query = urlencode(
        {
            key: value
            for key, value in (
                ("event_date", event_date.isoformat() if event_date else ""),
                ("size", filters.size or ""),
            )
            if value
        }
    )
    cards = [
        {
            "card": card,
            "thumb": image_url(storage, card.style.images[0]) if card.style.images else None,
            "href": f"/{card.shop.slug}/{card.style.code}"
            + (f"?{detail_query}" if detail_query else ""),
        }
        for card in results.cards
    ]
    shops = [
        {
            "card": shop_card,
            "thumb": image_url(storage, shop_card.cover.images[0])
            if shop_card.cover and shop_card.cover.images
            else None,
        }
        for shop_card in shop_cards(db, filters.city)
    ]
    return render(
        request,
        "home.html",
        {
            "filters": filters,
            "results": results,
            "cards": cards,
            "shops": shops,
            "sizes": sizes,
            "custom_size": CUSTOM_SIZE,
            "cities": cities,
            "categories": CATEGORY_LABELS,
            "price_caps": PRICE_CAPS,
            "sorts": SORT_LABELS,
            "date_error": date_error,
            "min_date": (today + timedelta(days=1)).isoformat(),
            "query": lambda **changes: _query(filters, **changes),
        },
    )


@router.get("/lang/{code}")
def set_language(code: str, next_: str = Query("/", alias="next")):
    response = RedirectResponse(safe_next(next_), status_code=303)
    if code in SUPPORTED_LOCALES:
        response.set_cookie(LOCALE_COOKIE, code, max_age=365 * 24 * 3600, samesite="lax")
    return response
