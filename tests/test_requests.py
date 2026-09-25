from datetime import timedelta

import pytest
from sqlalchemy import func, select

from tests.factories import make_booking, make_item, make_shop, make_shop_user, make_style
from twirl import clock
from twirl.booking.availability import style_availability
from twirl.booking.dates import derive_rental_dates
from twirl.booking.errors import InvalidDates, NoAvailability, ShopNotBookable
from twirl.booking.requests import RentalRequest, create_request
from twirl.booking.rules import rules_for_shop
from twirl.models import BookingEvent, Notification, ShopCustomer, User

EVENT = clock.today() + timedelta(days=30)


def _req(style, **kw):
    return RentalRequest(
        style_id=style.id,
        size=kw.pop("size", "38"),
        event_date=kw.pop("event_date", EVENT),
        name=kw.pop("name", "Arta"),
        phone=kw.pop("phone", "044 123 456"),
        **kw,
    )


def _setup(db, **shop_kw):
    shop = make_shop(db, **shop_kw)
    make_shop_user(db, shop, role="owner")
    style = make_style(db, shop)
    return shop, style


def test_request_mode_creates_pending_booking_event_and_notifications(db):
    _, style = _setup(db)
    item = make_item(db, style, size="38")
    booking = create_request(db, _req(style), today=clock.today())
    assert (booking.status, booking.kind, booking.item_id) == ("pending_shop", "online", item.id)
    assert booking.price_cents == style.price_cents
    events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == booking.id)).all()
    assert [(e.from_status, e.to_status, e.actor_kind) for e in events] == [
        (None, "pending_shop", "renter")
    ]
    assert sorted(n.channel for n in db.scalars(select(Notification))) == ["email", "telegram"]


def test_instant_mode_confirms_immediately(db):
    _, style = _setup(db, booking_mode="instant")
    make_item(db, style)
    assert create_request(db, _req(style), today=clock.today()).status == "confirmed"


def test_second_request_gets_the_second_dress(db):
    _, style = _setup(db)
    first, second = make_item(db, style), make_item(db, style)
    a = create_request(db, _req(style), today=clock.today())
    b = create_request(db, _req(style, phone="044 999 888"), today=clock.today())
    assert (a.item_id, b.item_id) == (first.id, second.id)


def test_no_free_dress_raises(db):
    shop, style = _setup(db)
    item = make_item(db, style)
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, item, pickup=dates.pickup, return_=dates.return_)
    with pytest.raises(NoAvailability):
        create_request(db, _req(style), today=clock.today())


def test_other_size_is_not_offered(db):
    _, style = _setup(db)
    make_item(db, style, size="40")
    with pytest.raises(NoAvailability):
        create_request(db, _req(style, size="38"), today=clock.today())


@pytest.mark.parametrize("shop_status, published", [("draft", True), ("published", False)])
def test_unpublished_shop_or_style_is_not_bookable(db, shop_status, published):
    shop = make_shop(db, status=shop_status)
    style = make_style(db, shop, published=published)
    make_item(db, style)
    with pytest.raises(ShopNotBookable):
        create_request(db, _req(style), today=clock.today())


def test_event_too_soon_is_rejected(db):
    _, style = _setup(db)
    make_item(db, style)
    with pytest.raises(InvalidDates) as exc:
        create_request(db, _req(style, event_date=clock.today()), today=clock.today())
    assert exc.value.code == "pickup_in_past"


def test_same_phone_reuses_renter_and_links_shop_once(db):
    shop, style = _setup(db)
    make_item(db, style)
    make_item(db, style)
    create_request(db, _req(style), today=clock.today())
    create_request(db, _req(style, name="Arta B."), today=clock.today())
    assert (
        db.scalar(select(func.count()).select_from(User).where(User.phone == "+38344123456")) == 1
    )
    assert (
        db.scalar(
            select(func.count()).select_from(ShopCustomer).where(ShopCustomer.shop_id == shop.id)
        )
        == 1
    )


def test_style_availability_reports_each_size(db):
    shop, style = _setup(db)
    taken = make_item(db, style, size="38")
    make_item(db, style, size="40")
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, taken, pickup=dates.pickup, return_=dates.return_)
    availability = style_availability(db, style, EVENT, today=clock.today())
    assert availability.dates == dates
    assert availability.sizes == {"38": False, "40": True}
    assert list(availability.sizes) == ["38", "40"]
