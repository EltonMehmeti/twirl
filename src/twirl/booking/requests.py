from dataclasses import dataclass
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from twirl.booking.actor import Actor
from twirl.booking.availability import free_items_stmt
from twirl.booking.dates import blocked_range, derive_rental_dates, validate_rental_dates
from twirl.booking.errors import NoAvailability, ShopNotBookable, is_exclusion_violation
from twirl.booking.rules import rules_for_shop
from twirl.booking.timeline import record_created
from twirl.catalog import normalize_size
from twirl.codes import new_booking_ref
from twirl.customers import get_or_create_customer, link_customer
from twirl.models import (
    ActorKind, Booking, BookingKind, BookingMode, BookingStatus, Item, ShopStatus, Style,
)
from twirl.notify.outbox import notify_admin, notify_shop_owners
from twirl.notify.payloads import booking_payload
from twirl.phones import normalize_phone


@dataclass(frozen=True)
class RentalRequest:
    style_id: int
    size: str
    event_date: date
    name: str
    phone: str
    note: str = ""


def create_request(
    session: Session, req: RentalRequest, *, today: date, max_attempts: int = 3
) -> Booking:
    style = session.get(Style, req.style_id)
    if style is None or not style.published or style.deleted_at is not None:
        raise ShopNotBookable()
    shop = style.shop
    if shop.status != ShopStatus.PUBLISHED.value:
        raise ShopNotBookable()

    rules = rules_for_shop(shop)
    dates = derive_rental_dates(req.event_date, rules)
    validate_rental_dates(dates, rules, today=today, event=req.event_date)
    start, end = blocked_range(dates, prep_days=rules.prep_days, cleaning_days=rules.cleaning_days)
    size = normalize_size(req.size)
    phone = normalize_phone(req.phone)
    customer = get_or_create_customer(session, phone=phone, name=req.name)
    status = (
        BookingStatus.CONFIRMED
        if shop.booking_mode == BookingMode.INSTANT.value
        else BookingStatus.PENDING_SHOP
    )

    for _ in range(max_attempts):
        item_id = session.scalar(
            free_items_stmt(start=start, end=end, style_id=style.id, size=size)
            .with_only_columns(Item.id)
            .order_by(Item.id)
            .limit(1)
            .with_for_update(skip_locked=True, of=Item)
        )
        if item_id is None:
            raise NoAvailability()
        booking = Booking(
            ref=new_booking_ref(session),
            shop_id=shop.id,
            style_id=style.id,
            item_id=item_id,
            customer_id=customer.id,
            kind=BookingKind.ONLINE.value,
            status=status.value,
            event_date=req.event_date,
            pickup_date=dates.pickup,
            return_date=dates.return_,
            prep_days=rules.prep_days,
            cleaning_days=rules.cleaning_days,
            source_channel="storefront",
            price_cents=style.price_cents,
            fee_cents=0,
            customer_note=req.note.strip()[:500],
        )
        try:
            with session.begin_nested():
                session.add(booking)
                session.flush()
        except IntegrityError as exc:
            if is_exclusion_violation(exc):
                continue
            raise
        record_created(session, booking, Actor(ActorKind.RENTER, customer.id))
        link_customer(session, shop_id=shop.id, user_id=customer.id)
        payload = booking_payload(booking)
        notify_shop_owners(session, shop.id, "new_request_shop", payload)
        notify_admin(session, "new_request_admin", payload)
        session.flush()
        return booking
    raise NoAvailability()
