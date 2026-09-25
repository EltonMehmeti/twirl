from datetime import timedelta

import pytest

from twirl import clock
from twirl.otp import (
    MAX_ATTEMPTS,
    MAX_SENDS_PER_HOUR,
    TooMany,
    TooSoon,
    issue_code,
    seconds_until_resend,
    verify_code,
)

PHONE = "+38344123456"
SECRET = "test-secret"


def _issue(db, now, purpose="signup"):
    return issue_code(db, phone=PHONE, purpose=purpose, now=now, secret=SECRET)


def test_code_is_six_digits_and_verifies_once(db):
    now = clock.now()
    code = _issue(db, now)
    assert len(code) == 6 and code.isdigit()
    assert verify_code(db, phone=PHONE, purpose="signup", code=code, now=now, secret=SECRET)
    assert not verify_code(db, phone=PHONE, purpose="signup", code=code, now=now, secret=SECRET)


def test_wrong_purpose_or_phone_fails(db):
    now = clock.now()
    code = _issue(db, now)
    assert not verify_code(db, phone=PHONE, purpose="login", code=code, now=now, secret=SECRET)
    assert not verify_code(
        db, phone="+38349000000", purpose="signup", code=code, now=now, secret=SECRET
    )


def test_code_expires_after_five_minutes(db):
    now = clock.now()
    code = _issue(db, now)
    later = now + timedelta(minutes=5, seconds=1)
    assert not verify_code(db, phone=PHONE, purpose="signup", code=code, now=later, secret=SECRET)


def test_attempts_are_limited(db):
    now = clock.now()
    code = _issue(db, now)
    for _ in range(MAX_ATTEMPTS):
        assert not verify_code(
            db,
            phone=PHONE,
            purpose="signup",
            code="000000" if code != "000000" else "111111",
            now=now,
            secret=SECRET,
        )
    assert not verify_code(db, phone=PHONE, purpose="signup", code=code, now=now, secret=SECRET)


def test_resend_waits_thirty_seconds(db):
    now = clock.now()
    _issue(db, now)
    assert seconds_until_resend(db, phone=PHONE, now=now + timedelta(seconds=10)) == 20
    with pytest.raises(TooSoon):
        _issue(db, now + timedelta(seconds=10))
    new_code = _issue(db, now + timedelta(seconds=31))
    assert verify_code(
        db,
        phone=PHONE,
        purpose="signup",
        code=new_code,
        now=now + timedelta(seconds=32),
        secret=SECRET,
    )


def test_sends_per_hour_are_capped(db):
    now = clock.now()
    for i in range(MAX_SENDS_PER_HOUR):
        _issue(db, now + timedelta(seconds=31 * i))
    with pytest.raises(TooMany):
        _issue(db, now + timedelta(seconds=31 * MAX_SENDS_PER_HOUR))
