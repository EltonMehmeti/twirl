from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl import clock
from twirl.booking.actor import SYSTEM
from twirl.booking.timeline import transition
from twirl.models import Booking, BookingKind, BookingStatus, Notification, NotificationStatus
from twirl.notify.outbox import notify_admin
from twirl.notify.payloads import booking_payload
from twirl.notify.senders import Sender
from twirl.notify.templates import render

MAX_ATTEMPTS = 5
NO_SHOW_GRACE_DAYS = 1
NOT_RETURNED_GRACE_DAYS = 3


def deliver_notifications(
    session: Session, *, senders: dict[str, Sender], base_url: str, limit: int = 50
) -> int:
    rows = session.scalars(
        select(Notification)
        .where(Notification.status == NotificationStatus.QUEUED.value)
        .order_by(Notification.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    sent = 0
    for row in rows:
        row.attempts += 1
        try:
            subject, body = render(row.template, row.payload, base_url=base_url)
            row.provider_id = senders[row.channel].send(row.recipient, subject, body)
        except Exception as exc:  # noqa: BLE001 - any delivery failure is recorded and retried
            row.last_error = str(exc)[:1000]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = NotificationStatus.FAILED.value
            continue
        row.status = NotificationStatus.SENT.value
        row.sent_at = clock.now()
        sent += 1
    session.flush()
    return sent


def expire_stale_requests(session: Session, *, now: datetime, sla_hours: int) -> int:
    cutoff = now - timedelta(hours=sla_hours)
    rows = session.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.PENDING_SHOP.value, Booking.created_at < cutoff
        )
    ).all()
    for booking in rows:
        transition(session, booking, BookingStatus.CANCELLED_BY_SHOP, actor=SYSTEM,
                   reason="no reply within SLA")
        notify_admin(session, "request_expired_admin", {**booking_payload(booking), "hours": sla_hours})
    return len(rows)


def mark_no_shows(session: Session, *, today: date) -> int:
    rows = session.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.CONFIRMED.value,
            Booking.kind != BookingKind.BLOCK.value,
            Booking.pickup_date < today - timedelta(days=NO_SHOW_GRACE_DAYS),
        )
    ).all()
    for booking in rows:
        transition(session, booking, BookingStatus.NO_SHOW, actor=SYSTEM, reason="pickup date passed")
    return len(rows)


def mark_not_returned(session: Session, *, today: date) -> int:
    rows = session.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.PICKED_UP.value,
            Booking.return_date < today - timedelta(days=NOT_RETURNED_GRACE_DAYS),
        )
    ).all()
    for booking in rows:
        transition(session, booking, BookingStatus.NOT_RETURNED, actor=SYSTEM, reason="return overdue")
    return len(rows)
