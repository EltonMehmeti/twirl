from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from tests.factories import make_shop, make_style
from twirl import clock
from twirl.models import PhoneCode


def test_shop_defaults_to_salon_and_unverified(db):
    shop = make_shop(db)
    db.refresh(shop)
    assert (shop.kind, shop.verified_at, shop.terms_accepted_at) == ("salon", None, None)


def test_shop_kind_is_constrained(db):
    with pytest.raises(IntegrityError), db.begin_nested():
        make_shop(db, kind="franchise")


def test_style_category_is_constrained(db):
    style = make_style(db, make_shop(db))
    style.category = "evening"
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        style.category = "party"
        db.flush()


def test_phone_code_row(db):
    code = PhoneCode(
        phone="+38344123456",
        purpose="signup",
        code_hash="x" * 64,
        expires_at=clock.now() + timedelta(minutes=5),
    )
    db.add(code)
    db.flush()
    db.refresh(code)
    assert (code.attempts, code.consumed_at) == (0, None)
