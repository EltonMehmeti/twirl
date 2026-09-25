from datetime import UTC, datetime

from tests.factories import make_user
from tests.helpers import PASSWORD, csrf_from, login
from twirl.auth.passwords import hash_password
from twirl.ratelimit import RateLimiter


def _login_post(client, email, password):
    token = csrf_from(client, "/login")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_shop_page_requires_login(client):
    response = client.get("/shop", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/shop"


def test_owner_logs_in_and_sees_shop(client, owner):
    login(client, owner.email)
    response = client.get("/shop")
    assert response.status_code == 200
    assert "Bella" in response.text


def test_wrong_password_is_rejected(client, owner):
    assert _login_post(client, owner.email, "nope").status_code == 400


def test_login_without_csrf_is_forbidden(client, owner):
    response = client.post("/login", data={"email": owner.email, "password": PASSWORD})
    assert response.status_code == 403


def test_blocked_user_cannot_log_in(client, db, owner):
    owner.blocked_at = datetime.now(UTC)
    db.flush()
    assert _login_post(client, owner.email, PASSWORD).status_code == 400


def test_user_without_shop_gets_403(client, db):
    user = make_user(db, kind="shop", password_hash=hash_password(PASSWORD))
    login(client, user.email)
    assert client.get("/shop").status_code == 403


def test_logout_ends_session(owner_client):
    token = csrf_from(owner_client, "/shop")
    owner_client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert owner_client.get("/shop", follow_redirects=False).status_code == 303


def test_login_is_rate_limited(client, owner):
    statuses = [_login_post(client, owner.email, "nope").status_code for _ in range(11)]
    assert statuses[-1] == 429


def test_rate_limiter_window():
    now = [0.0]
    limiter = RateLimiter(2, 60, clock=lambda: now[0])
    assert limiter.allow("k") and limiter.allow("k")
    assert not limiter.allow("k")
    now[0] = 61
    assert limiter.allow("k")
