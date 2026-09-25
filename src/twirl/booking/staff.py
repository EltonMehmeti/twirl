from datetime import date, timedelta

from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from twirl.booking.actor import Actor
from twirl.booking.availability import free_items_stmt, overlapping_bookings
from twirl.booking.dates import RentalDates, blocked_range
from twirl.booking.errors import InvalidDates, InvalidTransition, ItemConflict, is_exclusion_violation
from twirl.booking.timeline import record_created, transition
from twirl.codes import new_booking_ref
from twirl.customers import get_or_create_customer, link_customer
from twirl.models import (
    ACTIVE_STATUSES, Booking, BookingEvent, BookingKind, BookingStatus, ConditionKind, Item,
    ItemConditionEvent, ItemStatus, Shop,
)
from twirl.notify.outbox import notify_admin
from twirl.notify.payloads import booking_payload
from twirl.phones import normalize_phone

MAX_STAFF_RENTAL_DAYS = 30
OVERRIDABLE = {BookingStatus.PENDING_SHOP.value, BookingStatus.CONFIRMED.value}
SWAPPABLE = {
    BookingStatus.PENDING_SHOP.value, BookingStatus.CONFIRMED.value, BookingStatus.AT_RISK.value,
}


def find_item_by_code(session: Session, shop_id: int, code: str) -> Item | None:
    return session.scalar(
        select(Item).where(Item.shop_id == shop_id, Item.code == code.strip().upper())
    )


def _insert(session: Session, booking: Booking, start: date, end: date) -> None:
    try:
        with session.begin_nested():
            session.add(booking)
            session.flush()
    except IntegrityError as exc:
        if is_exclusion_violation(exc):
            raise ItemConflict(
                overlapping_bookings(session, booking.item_id, start, end), overridable=False
            ) from exc
        raise


def create_staff_booking(
    session: Session,
    *,
    shop: Shop,
    item: Item,
    pickup: date,
    return_: date,
    name: str,
    phone: str,
    actor: Actor,
    kind: BookingKind = BookingKind.WALK_IN,
    picked_up_now: bool = False,
    override_reason: str | None = None,
    note: str = "",
) -> Booking:
    if item.shop_id != shop.id:
        raise ValueError("item belongs to another shop")
    if return_ < pickup:
        raise InvalidDates("return_before_pickup")
    if (return_ - pickup).days > MAX_STAFF_RENTAL_DAYS:
        raise InvalidDates("too_long")
    phone_e164 = normalize_phone(phone)
    start, end = blocked_range(
        RentalDates(pickup, return_), prep_days=shop.prep_days, cleaning_days=shop.cleaning_days
    )

    conflicts = overlapping_bookings(session, item.id, start, end)
    if conflicts:
        overridable = all(
            c.kind == BookingKind.ONLINE.value and c.status in OVERRIDABLE for c in conflicts
        )
        reason = (override_reason or "").strip()
        if not overridable or not reason:
            raise ItemConflict(conflicts, overridable=overridable)
        for conflict in conflicts:
            if conflict.status == BookingStatus.PENDING_SHOP.value:
                transition(session, conflict, BookingStatus.DECLINED, actor=actor,
                           reason=f"item taken in store: {reason}")
            else:
                transition(session, conflict, BookingStatus.AT_RISK, actor=actor,
                           reason=f"item taken in store: {reason}")
                notify_admin(
                    session, "booking_at_risk_admin", {**booking_payload(conflict), "reason": reason}
                )

    customer = get_or_create_customer(session, phone=phone_e164, name=name)
    booking = Booking(
        ref=new_booking_ref(session),
        shop_id=shop.id,
        style_id=item.style_id,
        item_id=item.id,
        customer_id=customer.id,
        kind=kind.value,
        status=BookingStatus.CONFIRMED.value,
        pickup_date=pickup,
        return_date=return_,
        prep_days=shop.prep_days,
        cleaning_days=shop.cleaning_days,
        source_channel="staff",
        price_cents=item.style.price_cents,
        staff_note=note.strip()[:500],
        created_by=actor.id,
    )
    _insert(session, booking, start, end)
    record_created(session, booking, actor)
    link_customer(session, shop_id=shop.id, user_id=customer.id)
    if picked_up_now:
        transition(session, booking, BookingStatus.PICKED_UP, actor=actor)
    return booking


def create_block(
    session: Session, *, item: Item, starts_on: date, ends_on: date, reason: str, actor: Actor
) -> Booking:
    if ends_on < starts_on:
        raise InvalidDates("return_before_pickup")
    conflicts = overlapping_bookings(session, item.id, starts_on, ends_on)
    if conflicts:
        raise ItemConflict(conflicts, overridable=False)
    block = Booking(
        ref=new_booking_ref(session),
        shop_id=item.shop_id,
        style_id=item.style_id,
        item_id=item.id,
        kind=BookingKind.BLOCK.value,
        status=BookingStatus.CONFIRMED.value,
        pickup_date=starts_on,
        return_date=ends_on,
        prep_days=0,
        cleaning_days=0,
        source_channel="staff",
        reason=reason.strip()[:300],
        created_by=actor.id,
    )
    _insert(session, block, starts_on, ends_on)
    record_created(session, block, actor)
    return block


def cancel_block(session: Session, booking: Booking, actor: Actor) -> Booking:
    if booking.kind != BookingKind.BLOCK.value:
        raise ValueError("not a block")
    return transition(session, booking, BookingStatus.CANCELLED_BY_SHOP, actor=actor, reason="block removed")


def swap_candidates(session: Session, booking: Booking, limit: int = 20) -> list[Item]:
    start = booking.blocked_range.lower
    end = booking.blocked_range.upper - timedelta(days=1)
    stmt = (
        free_items_stmt(start=start, end=end, shop_id=booking.shop_id)
        .where(Item.id != booking.item_id)
        .order_by(
            case((Item.style_id == booking.style_id, 0), else_=1),
            case((Item.size == booking.item.size, 0), else_=1),
            Item.id,
        )
        .limit(limit)
    )
    return list(session.scalars(stmt))


def swap_item(session: Session, booking: Booking, new_item: Item, *, actor: Actor) -> Booking:
    if new_item.shop_id != booking.shop_id or new_item.status != ItemStatus.ACTIVE.value:
        raise ValueError("item not available in this shop")
    if booking.status not in SWAPPABLE:
        raise InvalidTransition(booking.status, "swap")
    old_code = booking.item.code
    old_status = booking.status
    new_status = BookingStatus.CONFIRMED.value if old_status == BookingStatus.AT_RISK.value else old_status
    try:
        with session.begin_nested():
            booking.item_id = new_item.id
            booking.style_id = new_item.style_id
            booking.status = new_status
            session.flush()
    except IntegrityError as exc:
        if is_exclusion_violation(exc):
            raise ItemConflict([], overridable=False) from exc
        raise
    session.add(
        BookingEvent(
            booking_id=booking.id, from_status=old_status, to_status=new_status,
            actor_id=actor.id, actor_kind=actor.kind.value,
            reason=f"swap {old_code} -> {new_item.code}",
        )
    )
    session.flush()
    session.expire(booking, ["item", "style"])
    return booking


def accept(session: Session, booking: Booking, actor: Actor) -> Booking:
    return transition(session, booking, BookingStatus.CONFIRMED, actor=actor)


def _require_reason(reason: str) -> str:
    reason = reason.strip()
    if not reason:
        raise ValueError("reason required")
    return reason[:300]


def decline(session: Session, booking: Booking, actor: Actor, reason: str) -> Booking:
    return transition(session, booking, BookingStatus.DECLINED, actor=actor, reason=_require_reason(reason))


def cancel_by_shop(session: Session, booking: Booking, actor: Actor, reason: str) -> Booking:
    return transition(
        session, booking, BookingStatus.CANCELLED_BY_SHOP, actor=actor, reason=_require_reason(reason)
    )


def mark_picked_up(session: Session, booking: Booking, actor: Actor) -> Booking:
    return transition(session, booking, BookingStatus.PICKED_UP, actor=actor)


def mark_no_show(session: Session, booking: Booking, actor: Actor) -> Booking:
    return transition(session, booking, BookingStatus.NO_SHOW, actor=actor)


def mark_returned(
    session: Session, booking: Booking, actor: Actor, *, ok: bool, note: str = ""
) -> Booking:
    if not ok:
        note = _require_reason(note)
    transition(session, booking, BookingStatus.COMPLETED, actor=actor, reason=note.strip())
    session.add(
        ItemConditionEvent(
            item_id=booking.item_id,
            booking_id=booking.id,
            kind=(ConditionKind.RETURNED_OK if ok else ConditionKind.RETURNED_ISSUE).value,
            note=note.strip(),
            created_by=actor.id,
        )
    )
    session.flush()
    return booking


def set_item_status(
    session: Session, item: Item, status: str, *, actor: Actor, today: date, note: str = ""
) -> list[Booking]:
    new_status = ItemStatus(status).value
    old_status = item.status
    item.status = new_status
    session.add(
        ItemConditionEvent(
            item_id=item.id, kind=ConditionKind.STATUS_CHANGE.value,
            note=note.strip() or f"{old_status} -> {new_status}", created_by=actor.id,
        )
    )
    session.flush()
    return list(
        session.scalars(
            select(Booking)
            .where(
                Booking.item_id == item.id,
                Booking.status.in_(ACTIVE_STATUSES),
                Booking.return_date >= today,
            )
            .order_by(Booking.pickup_date)
        )
    )
