from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session, joinedload

from twirl.models import (
    ACTIVE_STATUSES, Booking, BookingKind, BookingStatus, Item, ItemStatus, Style,
)


@dataclass
class TodayBoard:
    pending: list[Booking]
    at_risk: list[Booking]
    pickups_today: list[Booking]
    returns_today: list[Booking]
    overdue_pickups: list[Booking]
    overdue_returns: list[Booking]


def _bookings(session: Session, shop_id: int, *conditions, order=Booking.pickup_date) -> list[Booking]:
    stmt = (
        select(Booking)
        .where(Booking.shop_id == shop_id, Booking.kind != BookingKind.BLOCK.value, *conditions)
        .options(joinedload(Booking.item), joinedload(Booking.style), joinedload(Booking.customer))
        .order_by(order, Booking.id)
    )
    return list(session.scalars(stmt).unique())


def today_board(session: Session, shop_id: int, today: date) -> TodayBoard:
    s = BookingStatus
    return TodayBoard(
        pending=_bookings(session, shop_id, Booking.status == s.PENDING_SHOP.value, order=Booking.created_at),
        at_risk=_bookings(session, shop_id, Booking.status == s.AT_RISK.value),
        pickups_today=_bookings(session, shop_id, Booking.status == s.CONFIRMED.value, Booking.pickup_date == today),
        returns_today=_bookings(session, shop_id, Booking.status == s.PICKED_UP.value, Booking.return_date == today),
        overdue_pickups=_bookings(session, shop_id, Booking.status == s.CONFIRMED.value, Booking.pickup_date < today),
        overdue_returns=_bookings(
            session, shop_id,
            Booking.status.in_([s.PICKED_UP.value, s.NOT_RETURNED.value]), Booking.return_date < today,
        ),
    )


@dataclass
class CalendarRow:
    item: Item
    cells: list[Booking | None]


def week_calendar(session: Session, shop_id: int, start: date) -> tuple[list[date], list[CalendarRow]]:
    days = [start + timedelta(days=i) for i in range(7)]
    items = session.scalars(
        select(Item)
        .join(Style, Style.id == Item.style_id)
        .where(Item.shop_id == shop_id, Item.status != ItemStatus.RETIRED.value, Style.deleted_at.is_(None))
        .options(joinedload(Item.style))
        .order_by(Style.code, Item.size, Item.code)
    ).all()
    bookings = session.scalars(
        select(Booking).where(
            Booking.shop_id == shop_id,
            Booking.status.in_(ACTIVE_STATUSES),
            Booking.blocked_range.overlaps(Range(days[0], days[-1], bounds="[]")),
        )
    ).all()
    by_item: dict[int, list[Booking]] = defaultdict(list)
    for booking in bookings:
        by_item[booking.item_id].append(booking)
    rows = []
    for item in items:
        cells = [
            next(
                (b for b in by_item[item.id] if b.blocked_range.lower <= day < b.blocked_range.upper),
                None,
            )
            for day in days
        ]
        rows.append(CalendarRow(item=item, cells=cells))
    return days, rows
