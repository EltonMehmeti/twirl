"""Marketplace search: which dresses can a renter actually get for their event date."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, selectinload

from twirl.booking.availability import _range
from twirl.booking.dates import blocked_range, derive_rental_dates, validate_rental_dates
from twirl.booking.errors import InvalidDates
from twirl.booking.rules import rules_for_shop
from twirl.catalog import size_sort_key
from twirl.models import ACTIVE_STATUSES, Booking, Item, ItemStatus, Shop, ShopStatus, Style

PAGE_SIZE = 24
SORTS = ("newest", "price_asc", "price_desc")


@dataclass(frozen=True)
class Filters:
    event_date: date | None = None
    size: str | None = None
    city: str | None = None
    category: str | None = None
    max_price_cents: int | None = None
    sort: str = "newest"
    page: int = 1

    @property
    def active(self) -> bool:
        return any((self.event_date, self.size, self.city, self.category, self.max_price_cents))


@dataclass(frozen=True)
class Card:
    style: Style
    shop: Shop
    sizes: list[str]


@dataclass
class Results:
    cards: list[Card] = field(default_factory=list)
    total: int = 0
    page: int = 1
    pages: int = 1
    # True when a date was picked but no shop in the area can hand a dress out in time.
    date_unreachable: bool = False


def _published_styles():
    return (
        select(Style)
        .join(Shop, Shop.id == Style.shop_id)
        .where(
            Shop.status == ShopStatus.PUBLISHED.value,
            Style.published.is_(True),
            Style.deleted_at.is_(None),
        )
    )


def _free(start: date, end: date) -> ColumnElement[bool]:
    busy = (
        select(Booking.id)
        .where(
            Booking.item_id == Item.id,
            Booking.status.in_(ACTIVE_STATUSES),
            Booking.blocked_range.overlaps(_range(start, end)),
        )
        .exists()
    )
    return ~busy


def _date_condition(
    session: Session, event_date: date, city: str | None, *, today: date
) -> ColumnElement[bool] | None:
    """Each shop has its own pickup and cleaning rules, so each gets its own busy window.

    Returns None when no shop can serve the date at all (too soon, closed that week).
    """
    shops = session.scalars(
        select(Shop)
        .where(Shop.status == ShopStatus.PUBLISHED.value, *([Shop.city == city] if city else []))
        .options(selectinload(Shop.hours), selectinload(Shop.closures))
    ).all()
    windows: dict[tuple[date, date], list[int]] = {}
    for shop in shops:
        rules = rules_for_shop(shop)
        try:
            dates = derive_rental_dates(event_date, rules)
            validate_rental_dates(dates, rules, today=today, event=event_date)
        except InvalidDates:
            continue
        window = blocked_range(dates, prep_days=rules.prep_days, cleaning_days=rules.cleaning_days)
        windows.setdefault(window, []).append(shop.id)
    if not windows:
        return None
    return or_(
        *(and_(Item.shop_id.in_(ids), _free(start, end)) for (start, end), ids in windows.items())
    )


def _item_conditions(filters: Filters, date_condition) -> list[ColumnElement[bool]]:
    conditions = [Item.status == ItemStatus.ACTIVE.value]
    if filters.size:
        conditions.append(Item.size == filters.size)
    if date_condition is not None:
        conditions.append(date_condition)
    return conditions


def search(session: Session, filters: Filters, *, today: date) -> Results:
    date_condition = None
    if filters.event_date is not None:
        date_condition = _date_condition(session, filters.event_date, filters.city, today=today)
        if date_condition is None:
            return Results(date_unreachable=True)

    item_conditions = _item_conditions(filters, date_condition)
    stmt = _published_styles().where(
        exists(select(Item.id).where(Item.style_id == Style.id, *item_conditions))
    )
    if filters.city:
        stmt = stmt.where(Shop.city == filters.city)
    if filters.category:
        stmt = stmt.where(Style.category == filters.category)
    if filters.max_price_cents is not None:
        stmt = stmt.where(Style.price_cents <= filters.max_price_cents)

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(1, filters.page), pages)

    order = {
        "price_asc": (Style.price_cents.asc(), Style.id.desc()),
        "price_desc": (Style.price_cents.desc(), Style.id.desc()),
    }.get(filters.sort, (Style.created_at.desc(), Style.id.desc()))
    styles = session.scalars(
        stmt.order_by(*order)
        .limit(PAGE_SIZE)
        .offset((page - 1) * PAGE_SIZE)
        .options(selectinload(Style.images), selectinload(Style.shop))
    ).all()

    sizes: dict[int, set[str]] = {}
    if styles:
        rows = session.execute(
            select(Item.style_id, Item.size).where(
                Item.style_id.in_([s.id for s in styles]),
                *_item_conditions(Filters(), date_condition),
            )
        )
        for style_id, size in rows:
            sizes.setdefault(style_id, set()).add(size)
    cards = [
        Card(style=s, shop=s.shop, sizes=sorted(sizes.get(s.id, ()), key=size_sort_key))
        for s in styles
    ]
    return Results(cards=cards, total=total, page=page, pages=pages)


def size_options(session: Session) -> list[str]:
    rows = session.scalars(
        select(Item.size)
        .distinct()
        .join(Style, Style.id == Item.style_id)
        .join(Shop, Shop.id == Item.shop_id)
        .where(
            Item.status == ItemStatus.ACTIVE.value,
            Style.published.is_(True),
            Style.deleted_at.is_(None),
            Shop.status == ShopStatus.PUBLISHED.value,
        )
    )
    return sorted(rows, key=size_sort_key)


def city_options(session: Session) -> list[str]:
    """Only cities where someone has a dress online: an empty city is a dead end."""
    return list(
        session.scalars(
            _published_styles().with_only_columns(Shop.city).distinct().order_by(Shop.city)
        )
    )


@dataclass(frozen=True)
class ShopCard:
    shop: Shop
    dresses: int
    cover: Style | None


def shop_cards(session: Session, city: str | None = None, limit: int = 12) -> list[ShopCard]:
    count = func.count(Style.id).label("dresses")
    stmt = (
        _published_styles()
        .with_only_columns(Shop, count)
        .group_by(Shop.id)
        .order_by(count.desc(), Shop.name)
        .limit(limit)
    )
    if city:
        stmt = stmt.where(Shop.city == city)
    rows = session.execute(stmt).all()
    covers = {}
    if rows:
        newest = session.scalars(
            _published_styles()
            .where(Style.shop_id.in_([shop.id for shop, _ in rows]))
            .order_by(Style.shop_id, Style.created_at.desc(), Style.id.desc())
            .ext(distinct_on(Style.shop_id))
            .options(selectinload(Style.images))
        )
        covers = {style.shop_id: style for style in newest}
    return [ShopCard(shop=shop, dresses=n, cover=covers.get(shop.id)) for shop, n in rows]
