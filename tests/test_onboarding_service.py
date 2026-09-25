from datetime import date, time, timedelta

import pytest
from sqlalchemy import select

from tests.factories import make_shop, make_user
from tests.helpers import png_bytes
from twirl import clock
from twirl.booking.actor import Actor
from twirl.catalog import save_style_image
from twirl.models import ActorKind, Booking, Notification, ShopKind, ShopUser
from twirl.onboarding import (
    MIN_PHOTOS,
    OnboardingError,
    WeeklyHours,
    blocked_dates,
    contiguous_ranges,
    dress_errors,
    get_or_create_draft_style,
    month_grid,
    provider_errors,
    provider_shop,
    publish,
    save_provider,
    set_dress,
    set_price_and_dates,
    slugify,
    unique_slug,
    verify_provider_phone,
)
from twirl.storage import LocalStorage

HOURS = WeeklyHours(time(9), time(20), time(9), time(18), sunday_closed=True)
TODAY = clock.today()


def _provider(db, kind=ShopKind.SALON):
    user = verify_provider_phone(db, phone="+38344123456", now=clock.now())
    if kind == ShopKind.SALON:
        shop = save_provider(
            db,
            user=user,
            kind=kind,
            name="Sallon Dea",
            city="Ferizaj",
            address="Rr. Dëshmorët 14",
            whatsapp="044 111 222",
            hours=HOURS,
        )
    else:
        shop = save_provider(db, user=user, kind=kind, name="Elira Krasniqi", city="Prizren")
    return user, shop


def _style_with_photos(db, tmp_path, shop, count=MIN_PHOTOS):
    style = get_or_create_draft_style(db, shop, None)
    storage = LocalStorage(tmp_path)
    for _ in range(count):
        save_style_image(db, storage, style, png_bytes(60, 80))
    return style


@pytest.mark.parametrize(
    "text, slug",
    [("Sallon Nusërie Dea", "sallon-nuserie-dea"), ("Çelik & Co.", "celik-co"), ("!", "vesha")],
)
def test_slugify(text, slug):
    assert slugify(text) == slug


def test_unique_slug_skips_taken_and_reserved(db):
    make_shop(db, slug="dea")
    assert unique_slug(db, "Dea") == "dea-2"
    assert unique_slug(db, "Admin") == "admin-2"


def test_verify_phone_creates_provider_user_and_upgrades_renters(db):
    renter = make_user(db, kind="renter", phone="+38349000111", email=None)
    user = verify_provider_phone(db, phone="+38349000111", now=clock.now())
    assert user.id == renter.id
    assert (user.kind, user.phone_verified_at is not None) == ("shop", True)
    fresh = verify_provider_phone(db, phone="+38344555666", now=clock.now())
    assert fresh.kind == "shop"


def test_save_salon_creates_draft_shop_owner_and_hours(db):
    user, shop = _provider(db)
    assert (shop.kind, shop.status, shop.slug, shop.whatsapp, shop.phone) == (
        "salon",
        "draft",
        "sallon-dea",
        "+38344111222",
        "+38344123456",
    )
    link = db.scalar(select(ShopUser).where(ShopUser.user_id == user.id))
    assert (link.shop_id, link.role) == (shop.id, "owner")
    hours = {h.weekday: (h.opens, h.closes, h.closed) for h in shop.hours}
    assert hours[0] == (time(9), time(20), False)
    assert hours[5] == (time(9), time(18), False)
    assert hours[6][2] is True


def test_save_individual_hides_address_and_uses_own_phone(db):
    user, shop = _provider(db, ShopKind.INDIVIDUAL)
    assert (shop.kind, shop.address, shop.whatsapp, user.name) == (
        "individual",
        "",
        "+38344123456",
        "Elira Krasniqi",
    )


def test_saving_twice_updates_the_same_shop(db):
    user, shop = _provider(db)
    again = save_provider(
        db,
        user=user,
        kind=ShopKind.SALON,
        name="Sallon Dea 2",
        city="Prishtinë",
        address="Rr. Nënë Tereza 1",
        whatsapp="044 111 222",
        hours=HOURS,
    )
    assert again.id == shop.id and again.name == "Sallon Dea 2"


def test_provider_errors_are_collected():
    bad_hours = WeeklyHours(time(20), time(9), time(9), time(18))
    errors = provider_errors(
        ShopKind.SALON, name="Ab", city="Atlantis", address="", whatsapp="12", hours=bad_hours
    )
    assert set(errors) == {"salon_name", "city", "address", "whatsapp", "hours"}
    assert provider_errors(ShopKind.INDIVIDUAL, name="Elira", city="Pejë") == ["name"]


def test_draft_style_is_reused_until_published(db, tmp_path):
    _, shop = _provider(db)
    style = get_or_create_draft_style(db, shop, None)
    assert get_or_create_draft_style(db, shop, style.id).id == style.id
    other_shop = make_shop(db)
    assert get_or_create_draft_style(db, other_shop, style.id).id != style.id


def test_dress_needs_photos_category_and_size(db, tmp_path):
    _, shop = _provider(db)
    style = _style_with_photos(db, tmp_path, shop, count=2)
    assert set(dress_errors(db, style, ShopKind.SALON, category="", sizes=[])) == {
        "photos",
        "category",
        "sizes",
    }
    with pytest.raises(OnboardingError):
        set_dress(
            db,
            style,
            kind=ShopKind.SALON,
            category="evening",
            sizes=["38"],
            description="",
            internal_ref="",
        )


def test_individual_picks_exactly_one_size(db, tmp_path):
    _, shop = _provider(db, ShopKind.INDIVIDUAL)
    style = _style_with_photos(db, tmp_path, shop)
    assert dress_errors(db, style, ShopKind.INDIVIDUAL, category="bridal", sizes=["38", "40"]) == [
        "sizes"
    ]


def test_set_dress_names_style_and_syncs_items(db, tmp_path):
    _, shop = _provider(db)
    style = _style_with_photos(db, tmp_path, shop)
    set_dress(
        db,
        style,
        kind=ShopKind.SALON,
        category="evening",
        sizes=["38", "40"],
        description="Qëndisje dore",
        internal_ref="NR-38",
    )
    assert (style.name, style.category, style.internal_ref) == (
        "Fustan mbrëmjeje",
        "evening",
        "NR-38",
    )
    assert sorted(i.size for i in style.items if i.status == "active") == ["38", "40"]
    set_dress(
        db,
        style,
        kind=ShopKind.SALON,
        category="evening",
        sizes=["40", "CUSTOM"],
        description="",
        internal_ref="",
    )
    active = sorted(i.size for i in style.items if i.status == "active")
    assert active == ["40", "CUSTOM"]
    assert [i.size for i in style.items if i.status == "retired"] == ["38"]


def test_contiguous_ranges():
    d = date(2027, 5, 1)
    days = [d, d + timedelta(1), d + timedelta(2), d + timedelta(5)]
    assert contiguous_ranges(days) == [(d, d + timedelta(2)), (d + timedelta(5), d + timedelta(5))]


def test_price_and_dates_become_blocks_and_can_be_changed(db, tmp_path):
    user, shop = _provider(db)
    style = _style_with_photos(db, tmp_path, shop)
    set_dress(
        db,
        style,
        kind=ShopKind.SALON,
        category="evening",
        sizes=["38", "40"],
        description="",
        internal_ref="",
    )
    actor = Actor(ActorKind.SHOP, user.id)
    busy = [TODAY + timedelta(days=3), TODAY + timedelta(days=4), TODAY + timedelta(days=9)]
    set_price_and_dates(db, style, price_eur=55, blocked=busy, actor=actor, today=TODAY)
    assert style.price_cents == 5500
    blocks = db.scalars(
        select(Booking).where(Booking.kind == "block", Booking.status == "confirmed")
    )
    assert len(list(blocks)) == 4  # two ranges x two items
    assert blocked_dates(db, style) == set(busy)
    set_price_and_dates(
        db, style, price_eur=60, blocked=[TODAY + timedelta(days=9)], actor=actor, today=TODAY
    )
    assert blocked_dates(db, style) == {TODAY + timedelta(days=9)}


def test_price_bounds(db, tmp_path):
    user, shop = _provider(db)
    style = _style_with_photos(db, tmp_path, shop)
    with pytest.raises(OnboardingError):
        set_price_and_dates(
            db, style, price_eur=4, blocked=[], actor=Actor(ActorKind.SHOP, user.id), today=TODAY
        )


def test_publish_requires_terms_and_goes_live(db, tmp_path):
    user, shop = _provider(db)
    style = _style_with_photos(db, tmp_path, shop)
    set_dress(
        db,
        style,
        kind=ShopKind.SALON,
        category="bridal",
        sizes=["38"],
        description="",
        internal_ref="",
    )
    set_price_and_dates(
        db, style, price_eur=80, blocked=[], actor=Actor(ActorKind.SHOP, user.id), today=TODAY
    )
    with pytest.raises(OnboardingError):
        publish(db, shop=shop, style=style, accepted_terms=False, now=clock.now())
    publish(db, shop=shop, style=style, accepted_terms=True, now=clock.now())
    assert (shop.status, style.published) == ("published", True)
    assert shop.terms_accepted_at is not None and shop.onboarding_completed_at is not None
    alert = db.scalars(select(Notification)).one()
    assert alert.template == "provider_published_admin"
    assert provider_shop(db, user).id == shop.id


def test_month_grid_starts_on_monday():
    grid = month_grid(2027, 5)  # 1 May 2027 is a Saturday
    assert grid[:6] == [None, None, None, None, None, date(2027, 5, 1)]
    assert grid[-1] == date(2027, 5, 31)
    assert len(grid) % 7 == 0 or grid[-1] is not None
