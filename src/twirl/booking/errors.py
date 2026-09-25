from sqlalchemy.exc import IntegrityError


class BookingError(Exception):
    code = "booking_error"


class InvalidDates(BookingError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InvalidTransition(BookingError):
    code = "invalid_transition"

    def __init__(self, src: str, dst: str) -> None:
        super().__init__(f"{src} -> {dst}")
        self.src = src
        self.dst = dst


class NoAvailability(BookingError):
    code = "no_availability"


class ShopNotBookable(BookingError):
    code = "not_bookable"


class ItemConflict(BookingError):
    code = "item_conflict"

    def __init__(self, conflicts: list, overridable: bool) -> None:
        super().__init__(f"{len(conflicts)} conflicting booking(s)")
        self.conflicts = conflicts
        self.overridable = overridable


def is_exclusion_violation(exc: IntegrityError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == "23P01"
