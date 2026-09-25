from datetime import timedelta

from sqlalchemy import select

from tests.factories import make_booking, make_item, make_shop, make_style
from twirl import clock
from twirl.jobs import (
    MAX_ATTEMPTS,
    deliver_notifications,
    expire_stale_requests,
    mark_no_shows,
    mark_not_returned,
)
from twirl.models import Notification
from twirl.notify.outbox import notify_admin


class FakeSender:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    def send(self, recipient, subject, body):
        if self.fail:
            raise RuntimeError("boom")
        self.sent.append((recipient, subject, body))
        return "id-1"


def _item(db):
    return make_item(db, make_style(db, make_shop(db)))


PAYLOAD = {
    "ref": "ABC123",
    "status": "pending_shop",
    "shop_name": "Bella",
    "style_name": "Gown",
    "size": "38",
    "event_date": "15.05.2027",
}


def test_deliver_marks_sent(db):
    notify_admin(db, "new_request_admin", PAYLOAD)
    db.flush()
    telegram = FakeSender()
    assert (
        deliver_notifications(
            db, senders={"telegram": telegram, "email": FakeSender()}, base_url="https://t"
        )
        == 1
    )
    row = db.scalars(select(Notification)).one()
    assert (row.status, row.attempts, row.provider_id) == ("sent", 1, "id-1")
    assert "ABC123" in telegram.sent[0][2]


def test_deliver_retries_then_fails(db):
    notify_admin(db, "new_request_admin", PAYLOAD)
    db.flush()
    senders = {"telegram": FakeSender(fail=True), "email": FakeSender()}
    for _ in range(MAX_ATTEMPTS):
        deliver_notifications(db, senders=senders, base_url="")
    row = db.scalars(select(Notification)).one()
    assert (row.status, row.attempts, row.last_error) == ("failed", MAX_ATTEMPTS, "boom")


def test_stale_requests_are_cancelled_and_reported(db):
    now = clock.now()
    item = _item(db)
    pick = clock.today() + timedelta(days=20)
    stale = make_booking(
        db,
        item,
        pickup=pick,
        return_=pick,
        kind="online",
        status="pending_shop",
        created_at=now - timedelta(hours=25),
    )
    fresh = make_booking(
        db,
        item,
        pickup=pick + timedelta(days=5),
        return_=pick + timedelta(days=5),
        kind="online",
        status="pending_shop",
        created_at=now - timedelta(hours=2),
    )
    assert expire_stale_requests(db, now=now, sla_hours=24) == 1
    assert (stale.status, fresh.status) == ("cancelled_by_shop", "pending_shop")
    assert db.scalars(select(Notification)).one().template == "request_expired_admin"


def test_no_show_after_one_day_grace_and_blocks_untouched(db):
    today = clock.today()
    late = make_booking(
        db, _item(db), pickup=today - timedelta(days=2), return_=today - timedelta(days=1)
    )
    grace = make_booking(db, _item(db), pickup=today - timedelta(days=1), return_=today)
    block = make_booking(
        db,
        _item(db),
        pickup=today - timedelta(days=5),
        return_=today - timedelta(days=4),
        kind="block",
    )
    assert mark_no_shows(db, today=today) == 1
    assert (late.status, grace.status, block.status) == ("no_show", "confirmed", "confirmed")


def test_not_returned_after_three_days(db):
    today = clock.today()
    item = _item(db)
    overdue = make_booking(
        db,
        item,
        pickup=today - timedelta(days=8),
        return_=today - timedelta(days=4),
        status="picked_up",
    )
    recent = make_booking(
        db,
        _item(db),
        pickup=today - timedelta(days=5),
        return_=today - timedelta(days=2),
        status="picked_up",
    )
    assert mark_not_returned(db, today=today) == 1
    assert (overdue.status, recent.status) == ("not_returned", "picked_up")
