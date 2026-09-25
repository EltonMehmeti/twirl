import pytest


@pytest.mark.parametrize(
    "name",
    ["clash-display-600", "clash-display-700", "hanken-grotesk-400", "hanken-grotesk-600"],
)
def test_brand_fonts_are_served_as_woff2(client, name):
    response = client.get(f"/static/fonts/{name}.woff2")
    assert response.status_code == 200
    assert response.content[:4] == b"wOF2"


def test_design_stylesheet_carries_tokens(client):
    css = client.get("/static/vesha.css").text
    for token in ("--color-paper: #fafaf7", "--color-gold: #f2b01e", "--font-display", "Hanken Grotesk"):
        assert token in css


def test_brand_name_is_shown(client):
    assert "Vesha" in client.get("/").text
