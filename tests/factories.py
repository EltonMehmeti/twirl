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


from twirl.codes import new_item_code  # noqa: E402
from twirl.models import Item, Style  # noqa: E402


def make_style(db, shop, *, name="Silk gown", price_cents=5000, published=True, code=None):
    n = next(_seq)
    style = Style(
        shop_id=shop.id, code=code or f"S{n:04d}", name=name, price_cents=price_cents,
        published=published,
    )
    db.add(style)
    db.flush()
    return style


def make_item(db, style, *, size="38", status="active", code=None):
    item = Item(
        shop_id=style.shop_id, style_id=style.id, size=size, status=status,
        code=code or new_item_code(db, style.shop_id),
    )
    db.add(item)
    db.flush()
    return item
