from tests.factories import make_shop_user
from tests.helpers import csrf_from


def _post(client, path, data):
    token = csrf_from(client, "/")
    return client.post(path, data={**data, "csrf_token": token}, follow_redirects=False)


def test_provider_logs_in_with_phone_code(client, db, shop, sms):
    user = make_shop_user(db, shop, role="owner")
    user.phone = "+38344123456"
    db.flush()
    response = _post(client, "/login/telefoni", {"phone": "044 123 456"})
    assert (response.status_code, response.headers["location"]) == (303, "/login/kodi")
    response = _post(client, "/login/kodi", {"code": sms.last_code()})
    assert (response.status_code, response.headers["location"]) == (303, "/shop")
    assert client.get("/shop").status_code == 200


def test_unknown_phone_gets_no_sms_but_same_screen(client, sms):
    response = _post(client, "/login/telefoni", {"phone": "044 999 888"})
    assert response.headers["location"] == "/login/kodi"
    assert sms.sent == []


def test_wrong_code_is_rejected(client, db, shop, sms):
    user = make_shop_user(db, shop, role="owner")
    user.phone = "+38344123456"
    db.flush()
    _post(client, "/login/telefoni", {"phone": "044 123 456"})
    response = _post(
        client, "/login/kodi", {"code": "000000" if sms.last_code() != "000000" else "111111"}
    )
    assert response.status_code == 400


def test_invalid_phone_is_rejected(client, sms):
    assert _post(client, "/login/telefoni", {"phone": "123"}).status_code == 400


def test_every_login_link_lands_on_the_phone_login(client):
    response = client.get("/login?next=/shop/calendar", follow_redirects=False)
    assert response.headers["location"] == "/login/telefoni?next=%2Fshop%2Fcalendar"
    assert client.get("/login", follow_redirects=False).headers["location"] == "/login/telefoni"
    assert 'href="/login"' not in client.get("/").text


def _provider(db, shop):
    user = make_shop_user(db, shop, role="owner")
    user.phone = "+38344123456"
    db.flush()


def test_phone_login_returns_to_the_page_that_asked(client, db, shop, sms):
    _provider(db, shop)
    client.get("/login/telefoni?next=/shop/calendar")
    _post(client, "/login/telefoni", {"phone": "044 123 456"})
    response = _post(client, "/login/kodi", {"code": sms.last_code()})
    assert response.headers["location"] == "/shop/calendar"


def test_phone_login_refuses_to_return_to_another_site(client, db, shop, sms):
    _provider(db, shop)
    client.get("/login/telefoni?next=//evil.example")
    _post(client, "/login/telefoni", {"phone": "044 123 456"})
    assert _post(client, "/login/kodi", {"code": sms.last_code()}).headers["location"] == "/shop"
