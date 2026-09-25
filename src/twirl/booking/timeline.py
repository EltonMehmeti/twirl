from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from twirl.booking.actor import Actor
from twirl.booking.errors import InvalidTransition, ItemConflict, is_exclusion_violation
from twirl.booking.states import can_transition
from twirl.models import Booking, BookingEvent, BookingStatus


def record_created(session: Session, booking: Booking, actor: Actor) -> None:
    session.add(
        BookingEvent(
            booking_id=booking.id, from_status=None, to_status=booking.status,
            actor_id=actor.id, actor_kind=actor.kind.value, reason="",
        )
    )


def transition(
    session: Session, booking: Booking, to: BookingStatus, *, actor: Actor, reason: str = ""
) -> Booking:
    src = BookingStatus(booking.status)
    if not can_transition(src, to):
        raise InvalidTransition(src.value, to.value)
    try:
        with session.begin_nested():
            booking.status = to.value
            if reason:
                booking.reason = reason
            session.add(
                BookingEvent(
                    booking_id=booking.id, from_status=src.value, to_status=to.value,
                    actor_id=actor.id, actor_kind=actor.kind.value, reason=reason,
                )
            )
            session.flush()
    except IntegrityError as exc:
        if is_exclusion_violation(exc):
            raise ItemConflict([], overridable=False) from exc
        raise
    return booking
