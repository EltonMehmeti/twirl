from datetime import date

import pytest

from tests.helpers import csrf_from
from twirl.web.templating import format_date, format_money


def test_home_defaults_to_albanian(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'lang="sq"' in response.text
    assert "Gjej fustanin për eventin tënd" in response.text


def test_home_in_english_with_cookie(client):
    client.cookies.set("lang", "en")
    response = client.get("/")
    assert 'lang="en"' in response.text
    assert "Find the dress for your event" in response.text


def test_language_switch_sets_cookie_and_redirects(client):
    response = client.get("/lang/en?next=/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "lang=en" in response.headers["set-cookie"]


def test_language_switch_refuses_external_redirect(client):
    response = client.get("/lang/en?next=//evil.example", follow_redirects=False)
    assert response.headers["location"] == "/"


def test_pages_carry_a_csrf_token(client):
    assert len(csrf_from(client, "/")) > 20


@pytest.mark.parametrize(
    "cents, locale, expected",
    [(5500, "sq", "55 €"), (5500, "en", "€55"), (5550, "sq", "55,50 €"), (5550, "en", "€55.50")],
)
def test_format_money(cents, locale, expected):
    assert format_money(cents, locale) == expected


def test_format_date():
    assert format_date(date(2027, 5, 15)) == "15.05.2027"
