import itertools

from twirl.models import Shop, ShopUser, User

_seq = itertools.count(1)


def make_user(db, *, kind="shop", name="Test User", email=None, phone=None, password_hash=None):
    n = next(_seq)
    user = User(
        kind=kind,
        name=name,
        email=email if email is not None else f"user{n}@example.com",
        phone=phone,
        password_hash=password_hash,
    )
    db.add(user)
    db.flush()
    return user


def make_shop(db, *, slug=None, status="published", booking_mode="request", **fields):
    n = next(_seq)
    shop = Shop(
        slug=slug or f"shop-{n}",
        name=fields.pop("name", f"Shop {n}"),
        city=fields.pop("city", "Ferizaj"),
        status=status,
        booking_mode=booking_mode,
        **fields,
    )
    db.add(shop)
    db.flush()
    return shop


def make_shop_user(db, shop, *, role="owner", email=None, password_hash=None):
    user = make_user(db, kind="shop", email=email, password_hash=password_hash)
    db.add(ShopUser(shop_id=shop.id, user_id=user.id, role=role))
    db.flush()
    return user
