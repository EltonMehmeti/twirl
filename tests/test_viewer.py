import re

from tests.factories import make_item, make_style
from tests.helpers import png_bytes
from twirl.app import STATIC_DIR
from twirl.catalog import image_url, save_style_image

VIEWER_ASSETS = (
    "viewer.js",
    "photoswipe/photoswipe-lightbox.esm.min.js",
    "photoswipe/photoswipe.esm.min.js",
    "photoswipe/photoswipe.css",
)


def _dress(db, shop):
    style = make_style(db, shop, name="Red silk gown")
    make_item(db, style, size="38")
    return style


def test_each_photo_opens_the_viewer_at_its_stored_size(client, app, db, shop):
    style = _dress(db, shop)
    storage = app.state.storage
    large = save_style_image(db, storage, style, png_bytes(1500, 2000))
    small = save_style_image(db, storage, style, png_bytes(600, 800))
    page = client.get(f"/bella/{style.code}").text
    links = re.findall(r'<a href="([^"]+)" data-pswp-width="(\d+)" data-pswp-height="(\d+)"', page)
    # Stored photos are at most 1200 wide; a smaller upload keeps its own size.
    assert links == [
        (image_url(storage, large, "detail"), "1200", "1600"),
        (image_url(storage, small, "detail"), "600", "800"),
    ]
    assert 'aria-label="Hap foton 1 nga 2"' in page
    assert re.search(r'<script type="module" src="[^"]*/static/viewer\.js"></script>', page)
    stylesheet = r'<link rel="stylesheet" href="[^"]*/static/photoswipe/photoswipe\.css">'
    assert re.search(stylesheet, page)


def test_viewer_controls_are_translated(client, app, db, shop):
    style = _dress(db, shop)
    save_style_image(db, app.state.storage, style, png_bytes())
    page = client.get(f"/bella/{style.code}").text
    assert 'aria-label="Hap foton"' in page
    for attribute in (
        'data-close="Mbyll"',
        'data-full="Ekran i plotë"',
        'data-full-exit="Dil nga ekrani i plotë"',
        'data-zoom-in="Zmadho"',
        'data-zoom-out="Zvogëlo"',
        'data-prev="Fotoja e mëparshme"',
        'data-next="Fotoja tjetër"',
        'data-label="Fotot: Red silk gown"',
    ):
        assert attribute in page, attribute
    client.cookies.set("lang", "en")
    assert 'data-full="Full screen"' in client.get(f"/bella/{style.code}").text


def test_dress_without_photos_loads_no_viewer(client, db, shop):
    style = _dress(db, shop)
    page = client.get(f"/bella/{style.code}").text
    assert "viewer.js" not in page
    assert "photoswipe" not in page


def test_viewer_files_are_served(client):
    for path in VIEWER_ASSETS:
        assert client.get(f"/static/{path}").status_code == 200, path


def test_viewer_imports_resolve_to_vendored_files():
    source = (STATIC_DIR / "viewer.js").read_text()
    specifiers = re.findall(r"""(?:from|import\()\s*["'](\.[^"']+)["']""", source)
    assert len(specifiers) == 2, specifiers
    for specifier in specifiers:
        assert (STATIC_DIR / specifier).is_file(), specifier
