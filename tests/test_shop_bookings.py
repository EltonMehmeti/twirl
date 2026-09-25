from datetime import timedelta

from sqlalchemy import select

from tests.factories import make_booking, make_item, make_renter, make_shop, make_style
from tests.helpers import post
from twirl import clock
from twirl.booking.requests import RentalRequest, create_request
from twirl.models import Booking

T = clock.today()


def _pending(db, shop):
    style = make_style(db, shop)
    make_item(db, style, size="38")
    return create_request(
        db,
        RentalRequest(
            style_id=style.id,
            size="38",
            event_date=T + timedelta(days=20),
            name="Arta",
            phone="044 123 456",
        ),
        today=T,
    )


def test_today_lists_pending_requests(owner_client, db, shop):
    booking = _pending(db, shop)
    response = owner_client.get("/shop")
    assert response.status_code == 200
    assert booking.ref in response.text


def test_booking_page_offers_accept(owner_client, db, shop):
    booking = _pending(db, shop)
    response = owner_client.get(f"/shop/bookings/{booking.id}")
    assert response.status_code == 200
    assert f"/shop/bookings/{booking.id}/accept" in response.text


def test_accept_request(owner_client, db, shop):
    booking = _pending(db, shop)
    assert post(owner_client, f"/shop/bookings/{booking.id}/accept").status_code == 303
    assert booking.status == "confirmed"


def test_decline_needs_a_reason(owner_client, db, shop):
    booking = _pending(db, shop)
    assert post(owner_client, f"/shop/bookings/{booking.id}/decline").status_code == 400
    assert (
        post(
            owner_client, f"/shop/bookings/{booking.id}/decline", {"reason": "damaged"}
        ).status_code
        == 303
    )
    assert (booking.status, booking.reason) == ("declined", "damaged")


def test_impossible_action_is_409(owner_client, db, shop):
    booking = _pending(db, shop)
    assert post(owner_client, f"/shop/bookings/{booking.id}/picked-up").status_code == 409
    db.refresh(booking)
    assert booking.status == "pending_shop"


def test_other_shops_booking_is_404(owner_client, db):
    booking = _pending(db, make_shop(db))
    assert owner_client.get(f"/shop/bookings/{booking.id}").status_code == 404
    assert post(owner_client, f"/shop/bookings/{booking.id}/accept").status_code == 404


def _walk_in_data(item, **over):
    data = {
        "code": item.code.lower(),
        "kind": "walk_in",
        "pickup_date": T.isoformat(),
        "return_date": (T + timedelta(days=2)).isoformat(),
        "name": "Blerta",
        "phone": "044 555 666",
        "picked_up_now": "on",
    }
    data.update(over)
    return data


def test_walk_in_form_prefills_code(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    response = owner_client.get(f"/shop/walk-in?code={item.code}")
    assert response.status_code == 200
    assert f'value="{item.code}"' in response.text


def test_walk_in_created_and_picked_up(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    response = post(owner_client, "/shop/walk-in", _walk_in_data(item))
    assert response.status_code == 303
    booking = db.scalars(select(Booking).where(Booking.item_id == item.id)).one()
    assert (booking.kind, booking.status) == ("walk_in", "picked_up")


def test_walk_in_conflict_offers_override(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    online = make_booking(
        db,
        item,
        pickup=T + timedelta(days=5),
        return_=T + timedelta(days=7),
        kind="online",
        status="confirmed",
        customer=make_renter(db),
    )
    data = _walk_in_data(
        item,
        pickup_date=(T + timedelta(days=5)).isoformat(),
        return_date=(T + timedelta(days=6)).isoformat(),
        picked_up_now="",
    )
    first = post(owner_client, "/shop/walk-in", data)
    assert first.status_code == 409
    assert online.ref in first.text
    assert 'name="override_reason"' in first.text
    second = post(owner_client, "/shop/walk-in", {**data, "override_reason": "paid cash"})
    assert second.status_code == 303
    db.refresh(online)
    assert online.status == "at_risk"


def test_walk_in_unknown_code(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    assert post(owner_client, "/shop/walk-in", _walk_in_data(item, code="ZZZZ")).status_code == 400


def test_swap_via_route(owner_client, db, shop):
    style = make_style(db, shop)
    item, other = make_item(db, style), make_item(db, style)
    booking = make_booking(
        db,
        item,
        pickup=T + timedelta(days=3),
        return_=T + timedelta(days=4),
        kind="online",
        status="at_risk",
    )
    response = post(owner_client, f"/shop/bookings/{booking.id}/swap", {"item_id": str(other.id)})
    assert response.status_code == 303
    db.refresh(booking)
    assert (booking.item_id, booking.status) == (other.id, "confirmed")


def test_calendar_shows_block(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    make_booking(
        db,
        item,
        pickup=T + timedelta(days=1),
        return_=T + timedelta(days=2),
        kind="block",
        cleaning_days=0,
    )
    response = owner_client.get(f"/shop/calendar?start={T.isoformat()}")
    assert response.status_code == 200
    assert item.code in response.text
    assert 'data-kind="block"' in response.text
