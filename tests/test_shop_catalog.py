from datetime import timedelta

from sqlalchemy import func, select

from tests.factories import make_booking, make_item, make_shop, make_style
from tests.helpers import png_bytes, post
from twirl import clock
from twirl.models import Booking, Item, Style, StyleImage

T = clock.today()


def _style_data(**over):
    data = {"name": "Red silk gown", "price_eur": "55,50", "description": "",
            "occasion_tags": ["wedding", "matura"], "colour_family": "red", "length": "maxi",
            "published": "on"}
    data.update(over)
    return data


def test_owner_creates_style(owner_client, db, shop):
    response = post(owner_client, "/shop/styles/new", _style_data())
    assert response.status_code == 303
    style = db.scalars(select(Style).where(Style.shop_id == shop.id)).one()
    assert response.headers["location"] == f"/shop/styles/{style.id}"
    assert (style.code, style.price_cents, style.occasion_tags, style.colour_family, style.published) == (
        "001", 5550, ["wedding", "matura"], "red", True,
    )


def test_invalid_price_is_rejected(owner_client, db, shop):
    assert post(owner_client, "/shop/styles/new", _style_data(price_eur="abc")).status_code == 400
    assert db.scalar(select(func.count()).select_from(Style).where(Style.shop_id == shop.id)) == 0


def test_staff_cannot_create_styles(staff_client):
    assert staff_client.get("/shop/styles/new").status_code == 403


def test_owner_edits_style(owner_client, db, shop):
    style = make_style(db, shop, published=True)
    response = post(owner_client, f"/shop/styles/{style.id}", _style_data(name="New name", price_eur="60", published=""))
    assert response.status_code == 303
    assert (style.name, style.price_cents, style.published) == ("New name", 6000, False)


def test_staff_views_style_and_adds_items(staff_client, db, shop):
    style = make_style(db, shop)
    assert staff_client.get(f"/shop/styles/{style.id}").status_code == 200
    response = post(staff_client, f"/shop/styles/{style.id}/items", {"size": "38", "quantity": "2"})
    assert response.status_code == 303
    assert db.scalar(select(func.count()).select_from(Item).where(Item.style_id == style.id)) == 2


def test_photo_upload_is_processed_and_served(owner_client, db, shop, settings):
    style = make_style(db, shop)
    response = post(owner_client, f"/shop/styles/{style.id}/images",
                    files=[("files", ("a.png", png_bytes(), "image/png"))])
    assert response.status_code == 303
    image = db.scalars(select(StyleImage).where(StyleImage.style_id == style.id)).one()
    assert (settings.media_root / f"{image.storage_key}-thumb.webp").exists()
    assert owner_client.get(f"/media/{image.storage_key}-thumb.webp").status_code == 200


def test_garbage_upload_is_rejected(owner_client, db, shop):
    style = make_style(db, shop)
    response = post(owner_client, f"/shop/styles/{style.id}/images",
                    files=[("files", ("a.png", b"nope", "image/png"))])
    assert response.status_code == 400
    assert db.scalar(select(func.count()).select_from(StyleImage)) == 0


def test_other_shops_style_is_404(owner_client, db):
    style = make_style(db, make_shop(db))
    assert owner_client.get(f"/shop/styles/{style.id}").status_code == 404


def test_item_status_warns_about_future_bookings(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    make_booking(db, item, pickup=T + timedelta(days=5), return_=T + timedelta(days=6))
    response = post(owner_client, f"/shop/items/{item.id}/status", {"status": "repair"})
    assert response.status_code == 303
    assert response.headers["location"].endswith("?error=future_bookings")
    assert item.status == "repair"


def test_block_item_then_conflicting_block(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    data = {"starts_on": (T + timedelta(days=1)).isoformat(), "ends_on": (T + timedelta(days=2)).isoformat(),
            "reason": "repair"}
    assert post(owner_client, f"/shop/items/{item.id}/block", data).status_code == 303
    assert db.scalars(select(Booking).where(Booking.item_id == item.id)).one().kind == "block"
    second = post(owner_client, f"/shop/items/{item.id}/block", data)
    assert second.headers["location"].endswith("?error=block_conflict")


def test_item_qr_code(owner_client, db, shop):
    item = make_item(db, make_style(db, shop))
    response = owner_client.get(f"/shop/items/{item.id}/qr.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in response.text
