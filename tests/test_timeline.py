from datetime import date, timedelta

import pytest
from sqlalchemy import select

from tests.factories import make_booking, make_item, make_shop, make_style
from twirl.booking.actor import SYSTEM, Actor
from twirl.booking.errors import InvalidTransition, ItemConflict
from twirl.booking.states import can_transition
from twirl.booking.timeline import record_created, transition
from twirl.models import ActorKind, BookingEvent, BookingStatus

D = date(2027, 6, 1)
SHOP_ACTOR = Actor(ActorKind.SHOP)


def _events(db, booking):
    rows = db.scalars(
        select(BookingEvent).where(BookingEvent.booking_id == booking.id).order_by(BookingEvent.id)
    )
    return [(e.from_status, e.to_status, e.actor_kind, e.reason) for e in rows]


def _item(db):
    return make_item(db, make_style(db, make_shop(db)))


def test_allowed_transition_updates_status_and_logs_event(db):
    booking = make_booking(db, _item(db), pickup=D, return_=D, status="pending_shop", kind="online")
    transition(db, booking, BookingStatus.CONFIRMED, actor=SHOP_ACTOR, reason="ok")
    assert booking.status == "confirmed"
    assert _events(db, booking) == [("pending_shop", "confirmed", "shop", "ok")]


def test_disallowed_transition_raises_and_keeps_status(db):
    booking = make_booking(db, _item(db), pickup=D, return_=D, status="pending_shop", kind="online")
    with pytest.raises(InvalidTransition):
        transition(db, booking, BookingStatus.PICKED_UP, actor=SHOP_ACTOR)
    assert booking.status == "pending_shop"
    assert _events(db, booking) == []


@pytest.mark.parametrize(
    "terminal", ["completed", "declined", "expired", "no_show", "cancelled_by_renter", "cancelled_by_shop"]
)
def test_terminal_statuses_have_no_exits(terminal):
    assert not any(can_transition(BookingStatus(terminal), dst) for dst in BookingStatus)


def test_at_risk_cannot_return_to_confirmed_when_item_is_taken(db):
    item = _item(db)
    at_risk = make_booking(db, item, pickup=D, return_=D + timedelta(2), status="at_risk", kind="online")
    make_booking(db, item, pickup=D, return_=D + timedelta(2), status="confirmed")
    with pytest.raises(ItemConflict):
        transition(db, at_risk, BookingStatus.CONFIRMED, actor=SHOP_ACTOR)
    db.refresh(at_risk)
    assert at_risk.status == "at_risk"


def test_record_created_logs_initial_status(db):
    booking = make_booking(db, _item(db), pickup=D, return_=D)
    record_created(db, booking, SYSTEM)
    db.flush()
    assert _events(db, booking) == [(None, "confirmed", "system", "")]
