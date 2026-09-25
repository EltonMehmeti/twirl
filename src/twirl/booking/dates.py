from dataclasses import dataclass
from datetime import date, timedelta

from twirl.booking.errors import InvalidDates

MAX_ROLL_DAYS = 14


@dataclass(frozen=True)
class ShopRules:
    pickup_lead_days: int = 2
    return_after_days: int = 1
    prep_days: int = 0
    cleaning_days: int = 1
    max_rental_days: int = 7
    closed_weekdays: frozenset[int] = frozenset()
    closures: tuple[tuple[date, date], ...] = ()

    def is_open(self, day: date) -> bool:
        if day.weekday() in self.closed_weekdays:
            return False
        return not any(start <= day <= end for start, end in self.closures)


@dataclass(frozen=True)
class RentalDates:
    pickup: date
    return_: date


def _roll(day: date, step: int, rules: ShopRules) -> date:
    for _ in range(MAX_ROLL_DAYS):
        if rules.is_open(day):
            return day
        day += timedelta(days=step)
    raise InvalidDates("no_open_day")


def derive_rental_dates(event: date, rules: ShopRules) -> RentalDates:
    pickup = _roll(event - timedelta(days=rules.pickup_lead_days), -1, rules)
    return_ = _roll(event + timedelta(days=rules.return_after_days), 1, rules)
    return RentalDates(pickup, return_)


def validate_rental_dates(
    dates: RentalDates, rules: ShopRules, *, today: date, event: date | None = None
) -> None:
    if dates.pickup < today:
        raise InvalidDates("pickup_in_past")
    if dates.return_ < dates.pickup:
        raise InvalidDates("return_before_pickup")
    if (dates.return_ - dates.pickup).days > rules.max_rental_days:
        raise InvalidDates("too_long")
    if event is not None and not dates.pickup <= event <= dates.return_:
        raise InvalidDates("event_outside_rental")
    if not rules.is_open(dates.pickup):
        raise InvalidDates("pickup_closed")
    if not rules.is_open(dates.return_):
        raise InvalidDates("return_closed")


def blocked_range(dates: RentalDates, *, prep_days: int, cleaning_days: int) -> tuple[date, date]:
    return dates.pickup - timedelta(days=prep_days), dates.return_ + timedelta(days=cleaning_days)
