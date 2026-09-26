"""Sending SMS codes from web routes, shared by provider login and onboarding."""

from sqlalchemy.orm import Session
from starlette.requests import Request

from twirl import clock
from twirl.otp import issue_code, seconds_until_resend, sms_text

SESSION_ECHO = "otp_echo"


def send_code(request: Request, db: Session, phone: str, purpose: str) -> None:
    """Issue and send a code. Raises TooSoon or TooMany from twirl.otp."""
    settings = request.app.state.settings
    code = issue_code(db, phone=phone, purpose=purpose, now=clock.now(), secret=settings.secret_key)
    request.app.state.sms_sender.send(phone, "", sms_text(code, settings.brand_name))
    if settings.sms_dev_echo:
        request.session[SESSION_ECHO] = code


def resend_wait(db: Session, phone: str) -> int:
    return seconds_until_resend(db, phone=phone, now=clock.now())
