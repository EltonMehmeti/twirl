from datetime import timedelta

from sqlalchemy import func, select

from tests.factories import make_booking, make_item, make_shop, make_style
from tests.helpers import post
from twirl import clock
from twirl.booking.dates import derive_rental_dates
from twirl.booking.rules import rules_for_shop
from twirl.models import Booking

EVENT = clock.today() + timedelta(days=30)


def _dress(db, shop):
    style = make_style(db, shop, name="Red silk gown", price_cents=5500)
    return style, make_item(db, style, size="38"), make_item(db, style, size="40")


def _request_data(**over):
    data = {
        "event_date": EVENT.isoformat(),
        "size": "38",
        "name": "Arta",
        "phone": "044 123 456",
        "note": "Për maturë",
    }
    data.update(over)
    return data


def test_shop_page_lists_only_published_dresses(client, db, shop):
    _dress(db, shop)
    make_style(db, shop, name="Secret dress", published=False)
    response = client.get("/bella")
    assert response.status_code == 200
    assert "Red silk gown" in response.text
    assert "Secret dress" not in response.text


def test_draft_shop_is_hidden(client, db):
    make_shop(db, slug="draft-shop", status="draft")
    assert client.get("/draft-shop").status_code == 404


def test_style_page_has_sizes_and_share_tags(client, db, shop):
    style, _, _ = _dress(db, shop)
    response = client.get(f"/bella/{style.code}")
    assert response.status_code == 200
    assert 'property="og:title"' in response.text
    assert 'value="38"' in response.text and 'value="40"' in response.text


def test_availability_fragment_marks_taken_sizes(client, db, shop):
    style, item38, _ = _dress(db, shop)
    dates = derive_rental_dates(EVENT, rules_for_shop(shop))
    make_booking(db, item38, pickup=dates.pickup, return_=dates.return_)
    response = client.get(f"/bella/{style.code}/availability?event_date={EVENT.isoformat()}")
    assert response.status_code == 200
    assert '<li class="taken">38' in response.text
    assert '<li class="free">40' in response.text


def test_availability_for_too_soon_date_shows_error(client, db, shop):
    style, _, _ = _dress(db, shop)
    response = client.get(
        f"/bella/{style.code}/availability?event_date={clock.today().isoformat()}"
    )
    assert 'class="error"' in response.text


def test_request_creates_pending_booking_and_confirmation(client, db, shop, owner):
    style, _, _ = _dress(db, shop)
    response = post(client, f"/bella/{style.code}/request", _request_data())
    assert response.status_code == 303
    booking = db.scalars(select(Booking).where(Booking.shop_id == shop.id)).one()
    assert response.headers["location"] == f"/bella/r/{booking.ref}"
    assert (booking.status, booking.customer_note) == ("pending_shop", "Për maturë")
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert booking.ref in page.text


def test_confirmation_links_to_shop_whatsapp(client, db, shop):
    shop.whatsapp = "+38344111222"
    style, _, _ = _dress(db, shop)
    location = post(client, f"/bella/{style.code}/request", _request_data()).headers["location"]
    assert "https://wa.me/38344111222?text=" in client.get(location).text


def test_honeypot_silently_drops_bots(client, db, shop):
    style, _, _ = _dress(db, shop)
    response = post(
        client, f"/bella/{style.code}/request", _request_data(website="http://spam.example")
    )
    assert (response.status_code, response.headers["location"]) == (303, "/bella")
    assert db.scalar(select(func.count()).select_from(Booking)) == 0


def test_unavailable_size_is_409(client, db, shop):
    style, _, _ = _dress(db, shop)
    assert post(client, f"/bella/{style.code}/request", _request_data(size="42")).status_code == 409


def test_bad_phone_is_400(client, db, shop):
    style, _, _ = _dress(db, shop)
    assert (
        post(client, f"/bella/{style.code}/request", _request_data(phone="123")).status_code == 400
    )


def test_requests_are_rate_limited(client, db, shop):
    style, _, _ = _dress(db, shop)
    statuses = [
        post(client, f"/bella/{style.code}/request", _request_data(size="42")).status_code
        for _ in range(6)
    ]
    assert statuses == [409, 409, 409, 409, 409, 429]


def test_fixed_paths_are_not_shadowed(client):
    assert client.get("/login").status_code == 200
    assert client.get("/healthz").status_code == 200


def test_style_page_shows_promise_and_verified_badge(client, db, shop):
    from twirl import clock as _clock

    style, _, _ = _dress(db, shop)
    page = client.get(f"/bella/{style.code}").text
    assert "Si në foto." not in page and "Sallon i verifikuar" not in page
    shop.terms_accepted_at = shop.verified_at = _clock.now()
    db.flush()
    page = client.get(f"/bella/{style.code}").text
    assert "Si në foto." in page and "Sallon i verifikuar" in page
