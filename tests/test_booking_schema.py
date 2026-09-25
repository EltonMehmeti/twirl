from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from tests.factories import make_booking, make_item, make_shop, make_style

D = date(2027, 5, 10)


def _item(db):
    return make_item(db, make_style(db, make_shop(db)))


def test_blocked_range_includes_prep_and_cleaning_days(db):
    booking = make_booking(db, _item(db), pickup=D, return_=D + timedelta(2), prep_days=1, cleaning_days=1)
    db.refresh(booking)
    assert booking.blocked_range.lower == D - timedelta(1)
    assert booking.blocked_range.upper == D + timedelta(4)  # canonical form: upper bound exclusive


def test_overlapping_active_bookings_on_one_item_are_rejected(db):
    item = _item(db)
    make_booking(db, item, pickup=D, return_=D + timedelta(2))
    with pytest.raises(IntegrityError) as exc, db.begin_nested():
        make_booking(db, item, pickup=D + timedelta(1), return_=D + timedelta(3))
    assert exc.value.orig.sqlstate == "23P01"


def test_cleaning_day_blocks_the_next_pickup(db):
    item = _item(db)
    make_booking(db, item, pickup=D, return_=D + timedelta(1), cleaning_days=1)
    with pytest.raises(IntegrityError), db.begin_nested():
        make_booking(db, item, pickup=D + timedelta(2), return_=D + timedelta(3))
    make_booking(db, item, pickup=D + timedelta(3), return_=D + timedelta(4))


@pytest.mark.parametrize("status", ["cancelled_by_renter", "declined", "completed", "at_risk"])
def test_inactive_statuses_do_not_occupy_the_item(db, status):
    item = _item(db)
    make_booking(db, item, pickup=D, return_=D + timedelta(2), status=status)
    make_booking(db, item, pickup=D, return_=D + timedelta(2))


def test_same_dates_on_different_items_are_fine(db):
    style = make_style(db, make_shop(db))
    make_booking(db, make_item(db, style), pickup=D, return_=D + timedelta(2))
    make_booking(db, make_item(db, style), pickup=D, return_=D + timedelta(2))


def test_booking_style_must_match_item_style(db):
    shop = make_shop(db)
    item = make_item(db, make_style(db, shop))
    other_style = make_style(db, shop)
    booking = make_booking(db, item, pickup=D, return_=D)
    with pytest.raises(IntegrityError) as exc, db.begin_nested():
        booking.style_id = other_style.id
        db.flush()
    assert exc.value.orig.sqlstate == "23503"
