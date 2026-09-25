from tests.factories import make_item, make_style
from tests.helpers import post


def test_not_found_is_a_branded_page(client):
    r = client.get("/nope-shop-xyz")
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]
    assert "Vesha" in r.text and "detail" not in r.text


def test_dress_list_shows_piece_count(owner_client, db, shop):
    style = make_style(db, shop)
    make_item(db, style)
    make_item(db, style)
    page = owner_client.get("/shop/styles").text
    assert "built-in method" not in page
    assert "2 copë" in page


def test_settings_labels_are_translated(owner_client):
    page = owner_client.get("/shop/settings").text
    for english in ("Shop name", "Pickup: days before the event", "WhatsApp number"):
        assert english not in page


def test_failed_requests_do_not_use_up_the_limit(client, db, shop):
    style = make_style(db, shop)
    make_item(db, style, size="38")
    for _ in range(8):  # typos: invalid phone
        assert (
            post(
                client,
                f"/bella/{style.code}/request",
                {"event_date": "2099-01-10", "size": "38", "name": "Arta", "phone": "1"},
            ).status_code
            == 400
        )


def test_system_reasons_are_translated(owner_client, db, shop):
    from datetime import timedelta

    from tests.factories import make_booking, make_renter
    from twirl import clock

    item = make_item(db, make_style(db, shop))
    t = clock.today()
    online = make_booking(
        db,
        item,
        pickup=t + timedelta(5),
        return_=t + timedelta(7),
        kind="online",
        status="confirmed",
        customer=make_renter(db),
    )
    post(
        owner_client,
        "/shop/walk-in",
        {
            "code": item.code,
            "kind": "walk_in",
            "pickup_date": (t + timedelta(5)).isoformat(),
            "return_date": (t + timedelta(6)).isoformat(),
            "name": "Klient",
            "phone": "044 555 666",
            "override_reason": "paid cash",
        },
    )
    page = owner_client.get(f"/shop/bookings/{online.id}").text
    assert "item taken in store" not in page
    assert "Veshja u dha në dyqan" in page
