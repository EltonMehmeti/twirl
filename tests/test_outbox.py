from datetime import date

import pytest

from tests.factories import (
    make_booking,
    make_item,
    make_renter,
    make_shop,
    make_shop_user,
    make_style,
)
from twirl.models import Channel, Notification
from twirl.notify.outbox import enqueue, notify_admin, notify_shop_owners
from twirl.notify.payloads import booking_payload
from twirl.notify.templates import TEMPLATES, render


def test_notify_shop_owners_emails_owners_only(db):
    shop = make_shop(db)
    owner = make_shop_user(db, shop, role="owner")
    make_shop_user(db, shop, role="staff")
    rows = notify_shop_owners(db, shop.id, "new_request_shop", {"ref": "X"})
    db.flush()
    assert [(n.channel, n.recipient, n.status) for n in rows] == [("email", owner.email, "queued")]


def test_notify_admin_targets_admin_telegram(db):
    row = notify_admin(db, "new_request_admin", {"ref": "X"})
    db.flush()
    stored = db.get(Notification, row.id)
    assert (stored.channel, stored.recipient) == ("telegram", "admin")


def test_enqueue_rejects_unknown_template(db):
    with pytest.raises(KeyError):
        enqueue(db, channel=Channel.EMAIL, recipient="a@b.c", template="nope", payload={})


def test_booking_payload_and_every_template_render(db):
    shop = make_shop(db, name="Bella")
    style = make_style(db, shop, name="Red gown")
    item = make_item(db, style, size="38")
    booking = make_booking(
        db,
        item,
        pickup=date(2027, 5, 13),
        return_=date(2027, 5, 16),
        kind="online",
        status="pending_shop",
        customer=make_renter(db, name="Arta"),
        event_date=date(2027, 5, 15),
    )
    payload = booking_payload(booking)
    assert payload["pickup_date"] == "13.05.2027"
    assert payload["shop_name"] == "Bella"
    assert payload["customer_name"] == "Arta"
    assert payload["path"] == f"/shop/bookings/{booking.id}"
    provider_alerts = {"provider_published_admin", "provider_signed_up_admin"}
    for name in (t for t in TEMPLATES if t not in provider_alerts):
        subject, body = render(
            name, {**payload, "reason": "r", "hours": 24}, base_url="https://twirl.test"
        )
        assert booking.ref in subject + body
