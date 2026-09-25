import io
from dataclasses import dataclass

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
VARIANTS = {"thumb": 400, "detail": 1200}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}
ASPECT = 3 / 4


class InvalidImage(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProcessedImage:
    variants: dict[str, bytes]
    width: int
    height: int


def _crop_to_aspect(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width / height > ASPECT:
        new_width = round(height * ASPECT)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = round(width / ASPECT)
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def process_image(data: bytes) -> ProcessedImage:
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImage("too_large")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types for bad input
        raise InvalidImage("not_an_image") from exc
    if image.format not in ALLOWED_FORMATS:
        raise InvalidImage("unsupported_format")
    image = _crop_to_aspect(ImageOps.exif_transpose(image).convert("RGB"))

    variants: dict[str, bytes] = {}
    detail_size = image.size
    for name, target_width in VARIANTS.items():
        width = min(target_width, image.width)
        height = round(width / ASPECT)
        resized = image.resize((width, height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        resized.save(buffer, "WEBP", quality=80, method=4)
        variants[name] = buffer.getvalue()
        if name == "detail":
            detail_size = (width, height)
    return ProcessedImage(variants=variants, width=detail_size[0], height=detail_size[1])
