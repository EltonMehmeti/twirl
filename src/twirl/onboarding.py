"""Provider onboarding: from a verified phone to a published first listing.

Everything here flushes but never commits; the web layer owns the transaction.
"""

import calendar
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from twirl.booking.actor import Actor
from twirl.booking.staff import cancel_block, create_block
from twirl.catalog import add_items, next_style_code
from twirl.models import (
    Booking,
    BookingKind,
    BookingStatus,
    Item,
    ItemStatus,
    Shop,
    ShopHours,
    ShopKind,
    ShopRole,
    ShopStatus,
    ShopUser,
    Style,
    StyleCategory,
    StyleImage,
    User,
    UserKind,
)
from twirl.notify.outbox import notify_admin
from twirl.phones import InvalidPhone, normalize_phone
from twirl.slugs import is_valid_slug

CITIES = (
    "Prishtinë",
    "Prizren",
    "Pejë",
    "Gjakovë",
    "Gjilan",
    "Mitrovicë",
    "Ferizaj",
    "Vushtrri",
    "Podujevë",
    "Suharekë",
    "Rahovec",
    "Lipjan",
    "Fushë Kosovë",
    "Tjetër",
)
TERMS_VERSION = "2026-09-25"
MIN_PHOTOS = 3
MAX_PHOTOS = 8
PRICE_MIN_EUR = 5
PRICE_MAX_EUR = 2000
CUSTOM_SIZE = "CUSTOM"
SIZES = ("34", "36", "38", "40", "42", "44", "46", CUSTOM_SIZE)
BLOCK_REASON = "onboarding"
DRAFT_STYLE_NAME = "Veshje e re"
# Listing names are shop content, so they are Albanian regardless of UI language.
STYLE_NAMES = {
    StyleCategory.EVENING: "Fustan mbrëmjeje",
    StyleCategory.BRIDAL: "Fustan nusërie",
    StyleCategory.ENGAGEMENT: "Fustan fejese",
    StyleCategory.MENS_SUIT: "Kostum burrash",
    StyleCategory.TRADITIONAL: "Veshje tradicionale",
}


class OnboardingError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ── slugs ──────────────────────────────────────────────────────────────

_TRANSLIT = str.maketrans({"ë": "e", "Ë": "e", "ç": "c", "Ç": "c"})


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.translate(_TRANSLIT))
    text = text.encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = text[:50].strip("-")
    return text if len(text) >= 2 else "vesha"


def unique_slug(session: Session, name: str) -> str:
    base = slugify(name)
    candidate, n = base, 2
    while not is_valid_slug(candidate) or session.scalar(
        select(exists().where(Shop.slug == candidate))
    ):
        candidate = f"{base[:46]}-{n}"
        n += 1
    return candidate


# ── provider (user + shop) ─────────────────────────────────────────────


def verify_provider_phone(session: Session, *, phone: str, now: datetime) -> User:
    """Called after the SMS code checks out. Renters who start listing become providers."""
    user = session.scalar(select(User).where(User.phone == phone))
    if user is None:
        user = User(kind=UserKind.SHOP.value, name="", phone=phone)
        session.add(user)
    elif user.kind == UserKind.RENTER.value:
        user.kind = UserKind.SHOP.value
    user.phone_verified_at = now
    session.flush()
    return user


def provider_shop(session: Session, user: User) -> Shop | None:
    link = session.scalar(select(ShopUser).where(ShopUser.user_id == user.id))
    return session.get(Shop, link.shop_id) if link else None


@dataclass(frozen=True)
class WeeklyHours:
    weekday_open: time
    weekday_close: time
    saturday_open: time
    saturday_close: time
    sunday_closed: bool = True

    def valid(self) -> bool:
        return self.weekday_close > self.weekday_open and self.saturday_close > self.saturday_open


DEFAULT_HOURS = WeeklyHours(time(9), time(20), time(9), time(18), sunday_closed=True)


def weekly_hours(shop: Shop) -> WeeklyHours:
    rows = {h.weekday: h for h in shop.hours}
    weekday, saturday, sunday = rows.get(0), rows.get(5), rows.get(6)
    if not (weekday and saturday and weekday.opens and saturday.opens):
        return DEFAULT_HOURS
    return WeeklyHours(
        weekday.opens,
        weekday.closes,
        saturday.opens,
        saturday.closes,
        sunday_closed=bool(sunday is None or sunday.closed),
    )


def _clean_name(name: str) -> str:
    return " ".join(name.split())


def provider_errors(
    kind: ShopKind,
    *,
    name: str,
    city: str,
    address: str = "",
    whatsapp: str = "",
    hours: WeeklyHours | None = None,
) -> list[str]:
    """Every problem at once, so the form can mark all fields in one pass."""
    errors: list[str] = []
    name = _clean_name(name)
    if kind == ShopKind.INDIVIDUAL and len(name.split(" ")) < 2:
        errors.append("name")
    if kind == ShopKind.SALON and len(name) < 3:
        errors.append("salon_name")
    if kind == ShopKind.SALON and len(address.strip()) < 4:
        errors.append("address")
    if city not in CITIES:
        errors.append("city")
    if kind == ShopKind.SALON:
        try:
            normalize_phone(whatsapp)
        except InvalidPhone:
            errors.append("whatsapp")
        if hours is None or not hours.valid():
            errors.append("hours")
    return errors


def _apply_hours(shop: Shop, hours: WeeklyHours) -> None:
    existing = {row.weekday: row for row in shop.hours}
    for weekday in range(7):
        row = existing.get(weekday)
        if row is None:
            row = ShopHours(weekday=weekday)
            shop.hours.append(row)
        if weekday < 5:
            row.opens, row.closes, row.closed = hours.weekday_open, hours.weekday_close, False
        elif weekday == 5:
            row.opens, row.closes, row.closed = hours.saturday_open, hours.saturday_close, False
        else:
            row.opens, row.closes = hours.saturday_open, hours.saturday_close
            row.closed = hours.sunday_closed


def save_provider(
    session: Session,
    *,
    user: User,
    kind: ShopKind,
    name: str,
    city: str,
    address: str = "",
    whatsapp: str | None = None,
    hours: WeeklyHours | None = None,
) -> Shop:
    errors = provider_errors(
        kind, name=name, city=city, address=address, whatsapp=whatsapp or "", hours=hours
    )
    if errors:
        raise OnboardingError(errors[0])
    name = _clean_name(name)
    shop = provider_shop(session, user)
    is_new = shop is None
    if shop is None:
        shop = Shop(
            slug=unique_slug(session, name),
            name=name,
            city=city,
            kind=kind.value,
            status=ShopStatus.DRAFT.value,
        )
        session.add(shop)
        session.flush()
        session.add(ShopUser(shop_id=shop.id, user_id=user.id, role=ShopRole.OWNER.value))
    shop.name, shop.city, shop.kind = name, city, kind.value
    shop.phone = user.phone
    if kind == ShopKind.SALON:
        shop.address = address.strip()
        shop.whatsapp = normalize_phone(whatsapp or "")
        _apply_hours(shop, hours or DEFAULT_HOURS)
        user.name = user.name or name
    else:
        shop.address = ""
        shop.whatsapp = user.phone
        user.name = name
    if is_new:
        notify_admin(
            session,
            "provider_signed_up_admin",
            {
                "shop_name": shop.name,
                "kind": shop.kind,
                "city": shop.city,
                "phone": user.phone or "",
            },
        )
    session.flush()
    return shop


# ── the first item ─────────────────────────────────────────────────────


def get_or_create_draft_style(session: Session, shop: Shop, style_id: int | None) -> Style:
    if style_id:
        style = session.get(Style, style_id)
        if (
            style is not None
            and style.shop_id == shop.id
            and not style.published
            and style.deleted_at is None
        ):
            return style
    # Coming back another day: the session no longer knows the draft, so pick up the newest
    # unfinished one (photos and all) instead of starting over.
    existing = session.scalar(
        select(Style)
        .where(Style.shop_id == shop.id, Style.published.is_(False), Style.deleted_at.is_(None))
        .order_by(Style.id.desc())
        .limit(1)
    )
    if existing is not None:
        return existing
    style = Style(
        shop_id=shop.id,
        code=next_style_code(session, shop.id),
        name=DRAFT_STYLE_NAME,
        price_cents=0,
        published=False,
    )
    session.add(style)
    session.flush()
    return style


def photo_count(session: Session, style: Style) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(StyleImage).where(StyleImage.style_id == style.id)
        )
        or 0
    )


def active_items(style: Style) -> list[Item]:
    return [item for item in style.items if item.status == ItemStatus.ACTIVE.value]


def dress_errors(
    session: Session, style: Style, kind: ShopKind, *, category: str, sizes: list[str]
) -> list[str]:
    errors: list[str] = []
    if photo_count(session, style) < MIN_PHOTOS:
        errors.append("photos")
    if category not in {c.value for c in StyleCategory}:
        errors.append("category")
    chosen = list(dict.fromkeys(sizes))
    if not chosen or any(size not in SIZES for size in chosen):
        errors.append("sizes")
    elif kind == ShopKind.INDIVIDUAL and len(chosen) != 1:
        errors.append("sizes")
    return errors


def set_dress(
    session: Session,
    style: Style,
    *,
    kind: ShopKind,
    category: str,
    sizes: list[str],
    description: str,
    internal_ref: str,
) -> None:
    errors = dress_errors(session, style, kind, category=category, sizes=sizes)
    if errors:
        raise OnboardingError(errors[0])
    chosen = list(dict.fromkeys(sizes))
    style.category = category
    style.name = STYLE_NAMES[StyleCategory(category)]
    style.description = description.strip()[:2000]
    style.internal_ref = (internal_ref.strip()[:20] or None) if kind == ShopKind.SALON else None
    current = {item.size: item for item in active_items(style)}
    for size, item in current.items():
        if size not in chosen:
            item.status = ItemStatus.RETIRED.value  # never delete: blocks may point at it
    for size in chosen:
        if size not in current:
            add_items(session, style, size=size, quantity=1)
    session.flush()
    session.expire(style, ["items"])


# ── price and busy dates ───────────────────────────────────────────────


def contiguous_ranges(days: Iterable[date]) -> list[tuple[date, date]]:
    ranges: list[tuple[date, date]] = []
    for day in sorted(set(days)):
        if ranges and day == ranges[-1][1] + timedelta(days=1):
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
    return ranges


def _onboarding_blocks(session: Session, item: Item) -> list[Booking]:
    return list(
        session.scalars(
            select(Booking).where(
                Booking.item_id == item.id,
                Booking.kind == BookingKind.BLOCK.value,
                Booking.status == BookingStatus.CONFIRMED.value,
                Booking.reason == BLOCK_REASON,
            )
        )
    )


def blocked_dates(session: Session, style: Style) -> set[date]:
    items = active_items(style)
    if not items:
        return set()
    days: set[date] = set()
    for block in _onboarding_blocks(session, items[0]):
        day = block.pickup_date
        while day <= block.return_date:
            days.add(day)
            day += timedelta(days=1)
    return days


def set_price_and_dates(
    session: Session,
    style: Style,
    *,
    price_eur: int,
    blocked: Iterable[date],
    actor: Actor,
    today: date,
) -> None:
    if not PRICE_MIN_EUR <= price_eur <= PRICE_MAX_EUR:
        raise OnboardingError("price")
    style.price_cents = price_eur * 100
    ranges = contiguous_ranges(day for day in blocked if day >= today)
    for item in active_items(style):
        for block in _onboarding_blocks(session, item):
            cancel_block(session, block, actor)
        for start, end in ranges:
            create_block(
                session, item=item, starts_on=start, ends_on=end, reason=BLOCK_REASON, actor=actor
            )
    session.flush()


def month_grid(year: int, month: int) -> list[date | None]:
    """Days of one month, padded at the front so the first column is Monday."""
    first = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    return [None] * first.weekday() + [date(year, month, d) for d in range(1, days_in_month + 1)]


def next_months(today: date, count: int = 2) -> list[tuple[int, int]]:
    months, year, month = [], today.year, today.month
    for _ in range(count):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


# ── publish ────────────────────────────────────────────────────────────


def publish(
    session: Session, *, shop: Shop, style: Style, accepted_terms: bool, now: datetime
) -> None:
    if not accepted_terms:
        raise OnboardingError("terms")
    if (
        style.category is None
        or not active_items(style)
        or style.price_cents <= 0
        or photo_count(session, style) < MIN_PHOTOS
    ):
        raise OnboardingError("incomplete")
    style.published = True
    if shop.status == ShopStatus.DRAFT.value:
        shop.status = ShopStatus.PUBLISHED.value
    shop.terms_accepted_at = now
    shop.terms_version = TERMS_VERSION
    if shop.onboarding_completed_at is None:
        shop.onboarding_completed_at = now
    notify_admin(
        session,
        "provider_published_admin",
        {
            "shop_name": shop.name,
            "kind": shop.kind,
            "city": shop.city,
            "style_name": style.name,
            "path": f"/{shop.slug}/{style.code}",
        },
    )
    session.flush()
