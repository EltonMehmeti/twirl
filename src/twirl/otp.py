"""SMS verification codes: issue, rate-limit and verify.

Only an HMAC of (phone, code) is stored, keyed with the app secret, so a database leak does
not reveal live codes.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from twirl.models import CodePurpose, PhoneCode

CODE_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 3
RESEND_AFTER = timedelta(seconds=30)
MAX_SENDS_PER_HOUR = 5


class OtpError(Exception):
    code = "otp_error"


class TooSoon(OtpError):
    code = "too_soon"

    def __init__(self, seconds_left: int) -> None:
        super().__init__(f"wait {seconds_left}s")
        self.seconds_left = seconds_left


class TooMany(OtpError):
    code = "too_many"


def _hash(secret: str, phone: str, code: str) -> str:
    return hmac.new(secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _latest(session: Session, phone: str) -> PhoneCode | None:
    return session.scalar(
        select(PhoneCode)
        .where(PhoneCode.phone == phone)
        .order_by(PhoneCode.created_at.desc(), PhoneCode.id.desc())
        .limit(1)
    )


def seconds_until_resend(session: Session, *, phone: str, now: datetime) -> int:
    latest = _latest(session, phone)
    if latest is None:
        return 0
    remaining = (latest.created_at + RESEND_AFTER - now).total_seconds()
    return max(0, int(round(remaining)))


def issue_code(session: Session, *, phone: str, purpose: str, now: datetime, secret: str) -> str:
    wait = seconds_until_resend(session, phone=phone, now=now)
    if wait:
        raise TooSoon(wait)
    sent_last_hour = session.scalar(
        select(func.count())
        .select_from(PhoneCode)
        .where(PhoneCode.phone == phone, PhoneCode.created_at > now - timedelta(hours=1))
    )
    if sent_last_hour >= MAX_SENDS_PER_HOUR:
        raise TooMany()
    code = f"{secrets.randbelow(10**6):06d}"
    session.add(
        PhoneCode(
            phone=phone,
            purpose=CodePurpose(purpose).value,
            code_hash=_hash(secret, phone, code),
            expires_at=now + CODE_TTL,
            created_at=now,
        )
    )
    session.flush()
    return code


def verify_code(
    session: Session, *, phone: str, purpose: str, code: str, now: datetime, secret: str
) -> bool:
    """Check the newest live code for this phone and purpose. Every wrong guess counts."""
    row = session.scalar(
        select(PhoneCode)
        .where(
            PhoneCode.phone == phone,
            PhoneCode.purpose == purpose,
            PhoneCode.consumed_at.is_(None),
            PhoneCode.expires_at > now,
        )
        .order_by(PhoneCode.created_at.desc(), PhoneCode.id.desc())
        .limit(1)
        .with_for_update()
    )
    if row is None or row.attempts >= MAX_ATTEMPTS:
        return False
    row.attempts += 1
    ok = hmac.compare_digest(row.code_hash, _hash(secret, phone, code.strip()))
    if ok:
        row.consumed_at = now
    session.flush()
    return ok


def sms_text(code: str, brand: str) -> str:
    # No links in verification messages (spec §8.2).
    return f"{brand}: kodi juaj është {code}. Skadon pas 5 minutash."
