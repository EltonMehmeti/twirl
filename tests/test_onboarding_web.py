from datetime import timedelta

import pytest
from sqlalchemy import select

from tests.helpers import csrf_from, png_bytes
from twirl import clock
from twirl.models import Booking, Notification, Shop, Style, User


def _post(client, path, data=None, files=None):
    token = csrf_from(client, "/listo")
    return client.post(
        path, data={**(data or {}), "csrf_token": token}, files=files, follow_redirects=False
    )


def _verify(client, sms, path="salon", phone="044 123 456"):
    assert _post(client, "/listo", {"path": path}).headers["location"] == "/listo/telefoni"
    assert _post(client, "/listo/telefoni", {"phone": phone}).headers["location"] == "/listo/kodi"
    response = _post(client, "/listo/kodi", {"code": sms.last_code()})
    assert response.headers["location"] == "/listo/profili"


SALON = {
    "name": "Sallon Dea",
    "city": "Ferizaj",
    "address": "Rr. Dëshmorët 14",
    "whatsapp": "044 111 222",
    "wd_open": "09:00",
    "wd_close": "20:00",
    "sat_open": "09:00",
    "sat_close": "18:00",
    "sunday": "closed",
}


def _photos(client, n=3):
    for _ in range(n):
        response = _post(
            client,
            "/listo/veshja/foto",
            files=[("photo", ("a.png", png_bytes(60, 80), "image/png"))],
        )
        assert response.status_code == 200


def test_fork_page_renders_in_albanian(client):
    response = client.get("/listo")
    assert response.status_code == 200
    assert "Kush e jep veshjen me qera?" in response.text
    assert "vesha.css" in response.text


def test_steps_cannot_be_skipped(client, sms):
    assert client.get("/listo/veshja", follow_redirects=False).headers["location"] == "/listo"
    _post(client, "/listo", {"path": "salon"})
    assert (
        client.get("/listo/cmimi", follow_redirects=False).headers["location"] == "/listo/telefoni"
    )


def test_invalid_phone_and_wrong_code(client, sms):
    _post(client, "/listo", {"path": "individual"})
    assert _post(client, "/listo/telefoni", {"phone": "12"}).status_code == 400
    _post(client, "/listo/telefoni", {"phone": "044 123 456"})
    wrong = "000000" if sms.last_code() != "000000" else "111111"
    assert _post(client, "/listo/kodi", {"code": wrong}).status_code == 400


def test_salon_profile_validation_marks_every_field(client, sms):
    _verify(client, sms)
    response = _post(
        client,
        "/listo/profili",
        {**SALON, "name": "A", "address": "", "whatsapp": "1", "wd_close": "08:00"},
    )
    assert response.status_code == 400
    assert response.text.count("v-field--error") >= 4


def test_full_salon_flow_publishes_listing(client, db, sms):
    _verify(client, sms)
    assert _post(client, "/listo/profili", SALON).headers["location"] == "/listo/veshja"
    assert client.get("/listo/veshja").status_code == 200
    _photos(client)
    dress = {
        "category": "evening",
        "sizes": ["38", "40"],
        "description": "Qëndisje dore",
        "internal_ref": "NR-38",
    }
    assert _post(client, "/listo/veshja", dress).headers["location"] == "/listo/cmimi"
    busy = (clock.today() + timedelta(days=5)).isoformat()
    assert _post(client, "/listo/cmimi", {"price": "55", "busy": [busy]}).headers["location"] == (
        "/listo/permbledhja"
    )
    review = client.get("/listo/permbledhja")
    assert "Sallon Dea" in review.text and "NR-38" in review.text
    assert _post(client, "/listo/permbledhja").status_code == 400
    assert (
        _post(client, "/listo/permbledhja", {"terms": "yes"}).headers["location"] == "/listo/gati"
    )
    assert "Listimi i sallonit është live." in client.get("/listo/gati").text

    shop = db.scalar(select(Shop).where(Shop.slug == "sallon-dea"))
    style = db.scalar(select(Style).where(Style.shop_id == shop.id))
    assert (shop.status, shop.kind, style.published, style.price_cents) == (
        "published",
        "salon",
        True,
        5500,
    )
    blocks = db.scalars(select(Booking).where(Booking.shop_id == shop.id, Booking.kind == "block"))
    assert len(list(blocks)) == 2
    assert client.get(f"/sallon-dea/{style.code}").status_code == 200
    assert client.get("/shop").status_code == 200
    assert db.scalar(
        select(Notification).where(Notification.template == "provider_published_admin")
    )


def test_individual_flow_needs_one_size(client, db, sms):
    _verify(client, sms, path="individual", phone="049 555 666")
    assert (
        _post(client, "/listo/profili", {"name": "Elira Krasniqi", "city": "Prizren"}).status_code
        == 303
    )
    client.get("/listo/veshja")
    _photos(client)
    two = _post(client, "/listo/veshja", {"category": "bridal", "sizes": ["38", "40"]})
    assert two.status_code == 400
    assert (
        _post(client, "/listo/veshja", {"category": "bridal", "sizes": ["38"]}).status_code == 303
    )
    user = db.scalar(select(User).where(User.phone == "+38349555666"))
    assert user.name == "Elira Krasniqi" and user.phone_verified_at is not None


def test_too_few_photos_blocks_the_item_step(client, sms):
    _verify(client, sms)
    _post(client, "/listo/profili", SALON)
    client.get("/listo/veshja")
    _photos(client, 2)
    response = _post(client, "/listo/veshja", {"category": "evening", "sizes": ["38"]})
    assert response.status_code == 400


def test_photo_delete_and_garbage_upload(client, db, sms):
    _verify(client, sms)
    _post(client, "/listo/profili", SALON)
    client.get("/listo/veshja")
    _photos(client, 1)
    bad = _post(client, "/listo/veshja/foto", files=[("photo", ("a.png", b"nope", "image/png"))])
    assert bad.status_code == 400
    style = db.scalars(select(Style)).all()[-1]
    image_id = style.images[0].id
    assert _post(client, f"/listo/veshja/foto/{image_id}/fshi").status_code == 200
    db.refresh(style)
    assert style.images == []


@pytest.mark.parametrize("path", ["/listo/kodi", "/listo/profili", "/listo/gati"])
def test_anonymous_visitors_are_sent_to_the_start(client, path):
    assert client.get(path, follow_redirects=False).headers["location"] == "/listo"


def test_phone_page_works_on_english(client, sms):
    client.cookies.set("lang", "en")
    _post(client, "/listo", {"path": "salon"})
    assert "Phone number" in client.get("/listo/telefoni").text


def test_step_counter_is_translated(client, sms):
    _verify(client, sms)
    assert "Hapi 2 / 5" in client.get("/listo/profili").text
