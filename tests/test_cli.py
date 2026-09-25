import pytest
from sqlalchemy import select

from twirl.auth.passwords import verify_password
from twirl.cli import cmd_create_admin, cmd_create_shop, cmd_publish_shop
from twirl.models import ShopUser, User


def _shop(db, **over):
    kwargs = dict(
        slug="bella-2",
        name="Bella",
        city="Ferizaj",
        owner_email="Owner@Bella.test",
        owner_name="Drita",
        owner_password="pw-123456",
    )
    kwargs.update(over)
    return cmd_create_shop(db, **kwargs)


def test_create_shop_with_owner_and_staff(db):
    shop = _shop(db, staff_email="staff@bella.test", staff_password="pw-654321")
    assert shop.status == "draft"
    roles = sorted(db.scalars(select(ShopUser.role).where(ShopUser.shop_id == shop.id)))
    assert roles == ["owner", "staff"]
    owner = db.scalar(select(User).where(User.email == "owner@bella.test"))
    assert verify_password(owner.password_hash, "pw-123456")


def test_reserved_slug_is_rejected(db):
    with pytest.raises(ValueError):
        _shop(db, slug="admin")


def test_short_password_is_rejected(db):
    with pytest.raises(ValueError):
        _shop(db, owner_password="short")


def test_publish_shop(db):
    _shop(db)
    assert cmd_publish_shop(db, slug="bella-2").status == "published"


def test_create_admin(db):
    admin = cmd_create_admin(db, email="Me@Twirl.test", name="Me", password="pw-123456")
    assert (admin.kind, admin.email) == ("admin", "me@twirl.test")
