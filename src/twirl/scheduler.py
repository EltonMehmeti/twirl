import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from twirl import clock
from twirl.config import Settings
from twirl.db import Database
from twirl.jobs import (
    deliver_notifications,
    expire_stale_requests,
    mark_no_shows,
    mark_not_returned,
)
from twirl.notify.senders import build_senders

log = logging.getLogger(__name__)


def _run(db: Database, name: str, fn: Callable[..., int], kwargs: Callable[[], dict]) -> None:
    with db.sessionmaker() as session:
        try:
            count = fn(session, **kwargs())
            session.commit()
            if count:
                log.info("job %s processed %d row(s)", name, count)
        except Exception:
            session.rollback()
            log.exception("job %s failed", name)


def start_scheduler(db: Database, settings: Settings) -> BackgroundScheduler:
    """Run in exactly one process. With several web workers, enable it on one only."""
    senders = build_senders(settings)
    scheduler = BackgroundScheduler(timezone=clock.TZ)
    jobs = [
        (
            "deliver",
            deliver_notifications,
            lambda: {"senders": senders, "base_url": settings.base_url},
            {"seconds": 30},
        ),
        (
            "expire_requests",
            expire_stale_requests,
            lambda: {"now": clock.now(), "sla_hours": settings.request_sla_hours},
            {"minutes": 5},
        ),
        ("no_shows", mark_no_shows, lambda: {"today": clock.today()}, {"hours": 1}),
        ("not_returned", mark_not_returned, lambda: {"today": clock.today()}, {"hours": 1}),
    ]
    for name, fn, kwargs, interval in jobs:
        scheduler.add_job(
            _run,
            "interval",
            args=[db, name, fn, kwargs],
            id=name,
            max_instances=1,
            coalesce=True,
            **interval,
        )
    scheduler.start()
    return scheduler
