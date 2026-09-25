from datetime import date

from tests.factories import make_shop
from tests.helpers import post
from twirl.models import ShopClosure


def _data(**over):
    data = {
        "name": "Bella Dresses", "city": "Ferizaj", "address": "Rr. Dëshmorët 1",
        "phone": "044 111 222", "whatsapp": "044 111 222", "viber": "", "instagram": "bella.ks",
        "terms_text": "Depozitë 50 €", "pickup_lead_days": "2", "return_after_days": "1",
        "prep_days": "0", "cleaning_days": "2", "max_rental_days": "7",
    }
    data.update(over)
    return data


def test_owner_sees_settings(owner_client):
    response = owner_client.get("/shop/settings")
    assert response.status_code == 200
    assert 'name="cleaning_days"' in response.text


def test_staff_cannot_open_settings(staff_client):
    assert staff_client.get("/shop/settings").status_code == 403


def test_owner_saves_settings_and_closed_days(owner_client, shop):
    response = post(owner_client, "/shop/settings", {**_data(), "closed_weekdays": ["6"]})
    assert response.status_code == 303
    assert (shop.name, shop.cleaning_days, shop.whatsapp, shop.viber) == (
        "Bella Dresses", 2, "+38344111222", None,
    )
    assert [h.weekday for h in shop.hours if h.closed] == [6]


def test_invalid_settings_are_not_saved(owner_client, shop):
    response = post(owner_client, "/shop/settings", _data(cleaning_days="9"))
    assert response.status_code == 400
    assert shop.cleaning_days == 1


def test_invalid_phone_is_reported(owner_client, shop):
    response = post(owner_client, "/shop/settings", _data(phone="123"))
    assert response.status_code == 400


def test_add_and_delete_closure(owner_client, db, shop):
    response = post(owner_client, "/shop/settings/closures",
                    {"starts_on": "2027-08-01", "ends_on": "2027-08-10", "reason": "Pushime"})
    assert response.status_code == 303
    closure = db.query(ShopClosure).filter_by(shop_id=shop.id).one()
    assert (closure.starts_on, closure.ends_on) == (date(2027, 8, 1), date(2027, 8, 10))
    assert post(owner_client, f"/shop/settings/closures/{closure.id}/delete").status_code == 303
    assert db.query(ShopClosure).filter_by(shop_id=shop.id).count() == 0


def test_cannot_delete_another_shops_closure(owner_client, db):
    other = make_shop(db)
    closure = ShopClosure(shop_id=other.id, starts_on=date(2027, 1, 1), ends_on=date(2027, 1, 2))
    db.add(closure)
    db.flush()
    assert post(owner_client, f"/shop/settings/closures/{closure.id}/delete").status_code == 404


def test_closure_end_before_start_is_rejected(owner_client):
    response = post(owner_client, "/shop/settings/closures",
                    {"starts_on": "2027-08-10", "ends_on": "2027-08-01", "reason": ""})
    assert response.status_code == 400
