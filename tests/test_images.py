import io

import pytest
from PIL import Image

from tests.factories import make_shop, make_style
from tests.helpers import png_bytes
from twirl.catalog import MAX_IMAGES_PER_STYLE, image_url, save_style_image
from twirl.images import MAX_UPLOAD_BYTES, InvalidImage, process_image
from twirl.storage import LocalStorage


def _jpeg_with_exif() -> bytes:
    image = Image.new("RGB", (1600, 1200), (10, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


def test_variants_are_webp_3_by_4_and_exif_free():
    processed = process_image(_jpeg_with_exif())
    thumb = Image.open(io.BytesIO(processed.variants["thumb"]))
    detail = Image.open(io.BytesIO(processed.variants["detail"]))
    assert thumb.format == "WEBP" and thumb.size == (400, 533)
    assert detail.size == (900, 1200)
    assert (processed.width, processed.height) == (900, 1200)
    assert "exif" not in detail.info


def test_small_images_are_not_upscaled():
    processed = process_image(png_bytes(300, 400))
    assert Image.open(io.BytesIO(processed.variants["thumb"])).size == (300, 400)


def test_garbage_is_rejected():
    with pytest.raises(InvalidImage) as exc:
        process_image(b"not an image")
    assert exc.value.code == "not_an_image"


def test_oversized_upload_is_rejected():
    with pytest.raises(InvalidImage) as exc:
        process_image(b"0" * (MAX_UPLOAD_BYTES + 1))
    assert exc.value.code == "too_large"


def test_save_style_image_writes_variants(db, tmp_path):
    storage = LocalStorage(tmp_path)
    style = make_style(db, make_shop(db))
    image = save_style_image(db, storage, style, png_bytes())
    assert image.position == 0
    assert (tmp_path / f"{image.storage_key}-thumb.webp").exists()
    assert (tmp_path / f"{image.storage_key}-detail.webp").exists()
    assert image_url(storage, image) == f"/media/{image.storage_key}-thumb.webp"


def test_style_image_limit(db, tmp_path):
    storage = LocalStorage(tmp_path)
    style = make_style(db, make_shop(db))
    for _ in range(MAX_IMAGES_PER_STYLE):
        save_style_image(db, storage, style, png_bytes(60, 80))
    with pytest.raises(InvalidImage) as exc:
        save_style_image(db, storage, style, png_bytes(60, 80))
    assert exc.value.code == "too_many"


def test_storage_refuses_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).put("../escape.txt", b"x", "text/plain")
