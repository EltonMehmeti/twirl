import pytest
from sqlalchemy.exc import IntegrityError

from tests.factories import make_shop, make_shop_user
from twirl.models import ShopUser
from twirl.slugs import is_valid_slug


def test_shop_has_spec_default_rules(db):
    shop = make_shop(db)
    db.refresh(shop)
    assert (
        shop.pickup_lead_days,
        shop.return_after_days,
        shop.prep_days,
        shop.cleaning_days,
        shop.max_rental_days,
    ) == (2, 1, 0, 1, 7)
    assert shop.booking_mode == "request"


def test_slug_is_unique(db):
    make_shop(db, slug="bella")
    with pytest.raises(IntegrityError), db.begin_nested():
        make_shop(db, slug="bella")


def test_cleaning_days_range_is_enforced(db):
    with pytest.raises(IntegrityError), db.begin_nested():
        make_shop(db, cleaning_days=9)


def test_user_belongs_to_at_most_one_shop(db):
    shop_a = make_shop(db)
    shop_b = make_shop(db)
    user = make_shop_user(db, shop_a)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(ShopUser(shop_id=shop_b.id, user_id=user.id, role="staff"))
        db.flush()


@pytest.mark.parametrize(
    "slug, valid",
    [
        ("bella-dresses", True),
        ("b1", True),
        ("Bella", False),
        ("-bella", False),
        ("admin", False),
        ("shop", False),
        ("a", False),
    ],
)
def test_slug_validation(slug, valid):
    assert is_valid_slug(slug) is valid
