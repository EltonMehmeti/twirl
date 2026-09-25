"""Endpoints for an external scheduler, used when no in-process scheduler runs."""

import hmac

from fastapi import APIRouter, HTTPException, Request

from twirl import clock
from twirl.jobs import (
    deliver_notifications,
    expire_stale_requests,
    mark_no_shows,
    mark_not_returned,
)
from twirl.notify.senders import build_senders

router = APIRouter(prefix="/internal")


def _authorised(request: Request) -> None:
    secret = request.app.state.settings.cron_secret
    if not secret:
        raise HTTPException(status_code=404)
    sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(sent.encode(), secret.encode()):
        raise HTTPException(status_code=401)


@router.post("/jobs")
def run_jobs(request: Request) -> dict[str, int]:
    """Run every periodic job once. Each commits alone, so one failure can't block the rest."""
    _authorised(request)
    settings = request.app.state.settings
    senders = getattr(request.app.state, "senders", None) or build_senders(settings)
    request.app.state.senders = senders
    jobs = {
        "expire_requests": lambda s: expire_stale_requests(
            s, now=clock.now(), sla_hours=settings.request_sla_hours
        ),
        "no_shows": lambda s: mark_no_shows(s, today=clock.today()),
        "not_returned": lambda s: mark_not_returned(s, today=clock.today()),
        "deliver": lambda s: deliver_notifications(s, senders=senders, base_url=settings.base_url),
    }
    results: dict[str, int] = {}
    for name, job in jobs.items():
        with request.app.state.db.sessionmaker() as session:
            try:
                results[name] = job(session)
                session.commit()
            except Exception:  # noqa: BLE001 - report and continue with the next job
                session.rollback()
                results[name] = -1
    return results
