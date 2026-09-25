from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from twirl.app import create_app
from twirl.cli import cmd_create_admin


def test_admin_requires_login(client):
    response = client.get("/admin/", follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "/admin/login" in response.headers["location"]


def test_admin_login_and_lists(committed, settings):
    with sessionmaker(committed)() as session:
        cmd_create_admin(session, email="me@twirl.test", name="Me", password="pw-123456")
        session.commit()
    with TestClient(create_app(settings)) as admin_client:
        bad = admin_client.post("/admin/login", data={"username": "me@twirl.test", "password": "wrong"},
                                follow_redirects=False)
        assert bad.status_code == 400
        good = admin_client.post("/admin/login", data={"username": "me@twirl.test", "password": "pw-123456"},
                                 follow_redirects=False)
        assert good.status_code in (302, 303)
        for model in ("shop", "user", "style", "item", "booking", "booking-event", "notification"):
            assert admin_client.get(f"/admin/{model}/list").status_code == 200, model
