from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from twirl.booking.dates import RentalDates, blocked_range, derive_rental_dates, validate_rental_dates
from twirl.booking.rules import rules_for_shop
from twirl.catalog import size_sort_key
from twirl.models import ACTIVE_STATUSES, Booking, Item, ItemStatus, Style


def _range(start: date, end: date) -> Range[date]:
    return Range(start, end, bounds="[]")


def overlapping_bookings(session: Session, item_id: int, start: date, end: date) -> list[Booking]:
    return list(
        session.scalars(
            select(Booking)
            .where(
                Booking.item_id == item_id,
                Booking.status.in_(ACTIVE_STATUSES),
                Booking.blocked_range.overlaps(_range(start, end)),
            )
            .order_by(Booking.pickup_date)
        )
    )


def free_items_stmt(
    *, start: date, end: date, style_id: int | None = None, shop_id: int | None = None,
    size: str | None = None,
) -> Select:
    busy = (
        select(Booking.id)
        .where(
            Booking.item_id == Item.id,
            Booking.status.in_(ACTIVE_STATUSES),
            Booking.blocked_range.overlaps(_range(start, end)),
        )
        .exists()
    )
    stmt = select(Item).where(Item.status == ItemStatus.ACTIVE.value, ~busy)
    if style_id is not None:
        stmt = stmt.where(Item.style_id == style_id)
    if shop_id is not None:
        stmt = stmt.where(Item.shop_id == shop_id)
    if size is not None:
        stmt = stmt.where(Item.size == size)
    return stmt


@dataclass(frozen=True)
class StyleAvailability:
    dates: RentalDates
    sizes: dict[str, bool]


def style_availability(
    session: Session, style: Style, event_date: date, *, today: date
) -> StyleAvailability:
    rules = rules_for_shop(style.shop)
    dates = derive_rental_dates(event_date, rules)
    validate_rental_dates(dates, rules, today=today, event=event_date)
    start, end = blocked_range(dates, prep_days=rules.prep_days, cleaning_days=rules.cleaning_days)
    all_sizes = set(
        session.scalars(
            select(Item.size).where(
                Item.style_id == style.id, Item.status == ItemStatus.ACTIVE.value
            )
        )
    )
    free_sizes = set(
        session.scalars(
            free_items_stmt(start=start, end=end, style_id=style.id).with_only_columns(Item.size)
        )
    )
    ordered = sorted(all_sizes, key=size_sort_key)
    return StyleAvailability(dates=dates, sizes={s: s in free_sizes for s in ordered})
