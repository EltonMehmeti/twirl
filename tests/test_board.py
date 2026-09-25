from datetime import timedelta

from tests.factories import make_booking, make_item, make_shop, make_style
from twirl import clock
from twirl.booking.board import today_board, week_calendar

T = clock.today()


def test_today_board_groups_bookings(db):
    shop = make_shop(db)
    style = make_style(db, shop)
    items = [make_item(db, style) for _ in range(6)]
    pending = make_booking(db, items[0], pickup=T + timedelta(days=9), return_=T + timedelta(days=10),
                           kind="online", status="pending_shop")
    pickup = make_booking(db, items[1], pickup=T, return_=T + timedelta(days=2))
    returning = make_booking(db, items[2], pickup=T - timedelta(days=2), return_=T, status="picked_up")
    overdue = make_booking(db, items[3], pickup=T - timedelta(days=1), return_=T + timedelta(days=1))
    at_risk = make_booking(db, items[4], pickup=T + timedelta(days=3), return_=T + timedelta(days=4),
                           kind="online", status="at_risk")
    make_booking(db, items[5], pickup=T, return_=T, kind="block")
    board = today_board(db, shop.id, T)
    assert [b.id for b in board.pending] == [pending.id]
    assert [b.id for b in board.pickups_today] == [pickup.id]
    assert [b.id for b in board.returns_today] == [returning.id]
    assert [b.id for b in board.overdue_pickups] == [overdue.id]
    assert [b.id for b in board.at_risk] == [at_risk.id]


def test_week_calendar_places_bookings_including_cleaning_day(db):
    shop = make_shop(db)
    item = make_item(db, make_style(db, shop))
    booking = make_booking(db, item, pickup=T + timedelta(days=1), return_=T + timedelta(days=2), cleaning_days=1)
    days, rows = week_calendar(db, shop.id, T)
    assert len(days) == 7 and days[0] == T
    cells = rows[0].cells
    assert [c.id if c else None for c in cells[:5]] == [None, booking.id, booking.id, booking.id, None]
