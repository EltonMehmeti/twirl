from datetime import date

import pytest

from tests.factories import make_shop
from twirl.booking.dates import (
    RentalDates,
    ShopRules,
    blocked_range,
    derive_rental_dates,
    validate_rental_dates,
)
from twirl.booking.errors import InvalidDates
from twirl.booking.rules import rules_for_shop
from twirl.models import ShopClosure, ShopHours

SAT = date(2027, 5, 15)
TODAY = date(2027, 5, 1)


def test_fixture_date_is_a_saturday():
    assert SAT.weekday() == 5


def test_default_rules_pickup_two_days_before_return_one_day_after():
    assert derive_rental_dates(SAT, ShopRules()) == RentalDates(
        date(2027, 5, 13), date(2027, 5, 16)
    )


def test_return_rolls_forward_past_closed_sunday():
    rules = ShopRules(closed_weekdays=frozenset({6}))
    assert derive_rental_dates(SAT, rules).return_ == date(2027, 5, 17)


def test_pickup_rolls_back_past_a_closure():
    rules = ShopRules(closures=((date(2027, 5, 12), date(2027, 5, 13)),))
    assert derive_rental_dates(SAT, rules).pickup == date(2027, 5, 11)


def test_always_closed_shop_has_no_open_day():
    with pytest.raises(InvalidDates) as exc:
        derive_rental_dates(SAT, ShopRules(closed_weekdays=frozenset(range(7))))
    assert exc.value.code == "no_open_day"


def test_zero_lead_days_means_same_day_pickup_and_return():
    dates = derive_rental_dates(SAT, ShopRules(pickup_lead_days=0, return_after_days=0))
    assert dates == RentalDates(SAT, SAT)


@pytest.mark.parametrize(
    "pickup, return_, today, code",
    [
        (date(2027, 5, 13), date(2027, 5, 16), date(2027, 5, 14), "pickup_in_past"),
        (date(2027, 5, 16), date(2027, 5, 13), TODAY, "return_before_pickup"),
        (date(2027, 5, 1), date(2027, 5, 16), TODAY, "too_long"),
        (date(2027, 5, 16), date(2027, 5, 17), TODAY, "event_outside_rental"),
    ],
)
def test_validate_rejects_bad_dates(pickup, return_, today, code):
    with pytest.raises(InvalidDates) as exc:
        validate_rental_dates(RentalDates(pickup, return_), ShopRules(), today=today, event=SAT)
    assert exc.value.code == code


def test_validate_rejects_pickup_on_closed_day():
    rules = ShopRules(closed_weekdays=frozenset({3}))  # Thursday 13 May
    with pytest.raises(InvalidDates) as exc:
        validate_rental_dates(RentalDates(date(2027, 5, 13), date(2027, 5, 16)), rules, today=TODAY)
    assert exc.value.code == "pickup_closed"


def test_validate_accepts_derived_dates():
    rules = ShopRules()
    validate_rental_dates(derive_rental_dates(SAT, rules), rules, today=TODAY, event=SAT)


def test_blocked_range_applies_buffers():
    dates = RentalDates(date(2027, 5, 13), date(2027, 5, 16))
    assert blocked_range(dates, prep_days=1, cleaning_days=2) == (
        date(2027, 5, 12),
        date(2027, 5, 18),
    )


def test_rules_for_shop_reads_hours_and_closures(db):
    shop = make_shop(db, cleaning_days=2)
    shop.hours.append(ShopHours(weekday=6, closed=True))
    shop.closures.append(ShopClosure(starts_on=date(2027, 8, 1), ends_on=date(2027, 8, 10)))
    db.flush()
    rules = rules_for_shop(shop)
    assert rules.cleaning_days == 2
    assert rules.closed_weekdays == frozenset({6})
    assert rules.closures == ((date(2027, 8, 1), date(2027, 8, 10)),)
