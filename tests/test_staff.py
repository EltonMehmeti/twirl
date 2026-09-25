from datetime import timedelta

import pytest
from sqlalchemy import select

from tests.factories import make_booking, make_item, make_renter, make_shop, make_style
from twirl import clock
from twirl.booking.actor import Actor
from twirl.booking.errors import ItemConflict
from twirl.booking.staff import (
    cancel_block, create_block, create_staff_booking, decline, mark_returned, set_item_status,
    swap_candidates, swap_item,
)
from twirl.models import ActorKind, BookingEvent, ItemConditionEvent, Notification, ShopCustomer

PICK = clock.today() + timedelta(days=10)
RET = PICK + timedelta(days=2)
STAFF = Actor(ActorKind.SHOP)


def _setup(db):
    shop = make_shop(db)
    style = make_style(db, shop)
    return shop, style, make_item(db, style, size="38")


def _walk_in(db, shop, item, **kw):
    return create_staff_booking(
        db, shop=shop, item=item, pickup=kw.pop("pickup", PICK), return_=kw.pop("return_", RET),
        name="Blerta", phone="044 555 666", actor=STAFF, **kw,
    )


def test_walk_in_without_conflict_is_confirmed(db):
    shop, _, item = _setup(db)
    booking = _walk_in(db, shop, item)
    assert (booking.status, booking.kind, booking.customer.phone) == ("confirmed", "walk_in", "+38344555666")
    link = db.scalar(select(ShopCustomer).where(ShopCustomer.shop_id == shop.id))
    assert link.user_id == booking.customer_id


def test_walk_in_picked_up_now_goes_straight_to_picked_up(db):
    shop, _, item = _setup(db)
    booking = _walk_in(db, shop, item, picked_up_now=True)
    assert booking.status == "picked_up"
    events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == booking.id).order_by(BookingEvent.id))
    assert [(e.from_status, e.to_status) for e in events] == [(None, "confirmed"), ("confirmed", "picked_up")]


def test_conflict_with_online_booking_requires_a_reason(db):
    shop, _, item = _setup(db)
    online = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="confirmed")
    with pytest.raises(ItemConflict) as exc:
        _walk_in(db, shop, item)
    assert exc.value.overridable
    assert [b.id for b in exc.value.conflicts] == [online.id]


def test_override_flags_online_booking_at_risk_and_alerts_admin(db):
    shop, _, item = _setup(db)
    online = make_booking(
        db, item, pickup=PICK, return_=RET, kind="online", status="confirmed", customer=make_renter(db)
    )
    walk_in = _walk_in(db, shop, item, override_reason="customer paid cash")
    db.refresh(online)
    assert (online.status, walk_in.status) == ("at_risk", "confirmed")
    alert = db.scalars(select(Notification).where(Notification.template == "booking_at_risk_admin")).one()
    assert alert.payload["ref"] == online.ref
    assert alert.payload["reason"] == "customer paid cash"


def test_override_declines_a_pending_request(db):
    shop, _, item = _setup(db)
    pending = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="pending_shop")
    _walk_in(db, shop, item, override_reason="walk-in")
    db.refresh(pending)
    assert pending.status == "declined"


def test_staff_booking_cannot_be_overridden(db):
    shop, _, item = _setup(db)
    make_booking(db, item, pickup=PICK, return_=RET, kind="walk_in", status="confirmed")
    with pytest.raises(ItemConflict) as exc:
        _walk_in(db, shop, item, override_reason="please")
    assert not exc.value.overridable


def test_block_prevents_bookings_until_cancelled(db):
    shop, _, item = _setup(db)
    block = create_block(db, item=item, starts_on=PICK, ends_on=RET, reason="repair", actor=STAFF)
    assert (block.kind, block.customer_id, block.cleaning_days) == ("block", None, 0)
    with pytest.raises(ItemConflict) as exc:
        _walk_in(db, shop, item, override_reason="x")
    assert not exc.value.overridable
    cancel_block(db, block, STAFF)
    assert _walk_in(db, shop, item).status == "confirmed"


def test_swap_at_risk_booking_to_free_item_confirms_it(db):
    _, style, item = _setup(db)
    other = make_item(db, style, size="38")
    online = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="at_risk")
    swap_item(db, online, other, actor=STAFF)
    db.refresh(online)
    assert (online.item_id, online.status) == (other.id, "confirmed")
    last = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == online.id).order_by(BookingEvent.id.desc())).first()
    assert last.reason == f"swap {item.code} -> {other.code}"


def test_swap_to_busy_item_raises_and_changes_nothing(db):
    shop, style, item = _setup(db)
    other = make_item(db, style, size="38")
    make_booking(db, other, pickup=PICK, return_=RET, kind="walk_in")
    online = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="confirmed")
    with pytest.raises(ItemConflict):
        swap_item(db, online, other, actor=STAFF)
    db.refresh(online)
    assert online.item_id == item.id


def test_swap_candidates_prefer_same_style_then_same_size(db):
    shop, style, item = _setup(db)
    same = make_item(db, style, size="38")
    other_size = make_item(db, style, size="40")
    other_style = make_item(db, make_style(db, shop), size="38")
    booking = make_booking(db, item, pickup=PICK, return_=RET)
    assert [i.id for i in swap_candidates(db, booking)] == [same.id, other_size.id, other_style.id]


def test_return_with_issue_logs_condition(db):
    _, _, item = _setup(db)
    booking = make_booking(db, item, pickup=PICK, return_=RET, status="picked_up")
    mark_returned(db, booking, STAFF, ok=False, note="stain on hem")
    assert booking.status == "completed"
    event = db.scalars(select(ItemConditionEvent)).one()
    assert (event.kind, event.note, event.booking_id) == ("returned_issue", "stain on hem", booking.id)


def test_decline_requires_a_reason(db):
    _, _, item = _setup(db)
    booking = make_booking(db, item, pickup=PICK, return_=RET, kind="online", status="pending_shop")
    with pytest.raises(ValueError):
        decline(db, booking, STAFF, "   ")


def test_set_item_status_returns_future_bookings(db):
    _, _, item = _setup(db)
    booking = make_booking(db, item, pickup=PICK, return_=RET)
    future = set_item_status(db, item, "repair", actor=STAFF, today=clock.today())
    assert item.status == "repair"
    assert [b.id for b in future] == [booking.id]
    assert db.scalars(select(ItemConditionEvent)).one().kind == "status_change"
