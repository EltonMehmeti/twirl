from collections.abc import Iterable

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from twirl.codes import new_item_code
from twirl.models import ColourFamily, DressLength, Item, Occasion, Shop, Style

LETTER_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]
MAX_ITEMS_PER_ADD = 20


def normalize_size(raw: str) -> str:
    size = raw.strip().upper()
    if not size or len(size) > 8:
        raise ValueError("invalid size")
    return size


def size_sort_key(size: str) -> tuple[int, float, str]:
    if size.replace(".", "", 1).isdigit():
        return (0, float(size), size)
    if size in LETTER_SIZES:
        return (1, float(LETTER_SIZES.index(size)), size)
    return (2, 0.0, size)


def next_style_code(session: Session, shop_id: int) -> str:
    n = session.scalar(select(func.count()).select_from(Style).where(Style.shop_id == shop_id)) or 0
    while True:
        n += 1
        code = f"{n:03d}"
        taken = session.scalar(select(exists().where(Style.shop_id == shop_id, Style.code == code)))
        if not taken:
            return code


def create_style(
    session: Session,
    shop: Shop,
    *,
    name: str,
    price_cents: int,
    description: str = "",
    occasion_tags: Iterable[str] = (),
    colour_family: str | None = None,
    length: str | None = None,
    stretch: bool = False,
    adjustable_back: bool = False,
    published: bool = False,
) -> Style:
    tags = [Occasion(tag).value for tag in occasion_tags]
    style = Style(
        shop_id=shop.id,
        code=next_style_code(session, shop.id),
        name=name.strip(),
        price_cents=price_cents,
        description=description.strip(),
        occasion_tags=tags,
        colour_family=ColourFamily(colour_family).value if colour_family else None,
        length=DressLength(length).value if length else None,
        stretch=stretch,
        adjustable_back=adjustable_back,
        published=published,
    )
    session.add(style)
    session.flush()
    return style


def add_items(session: Session, style: Style, *, size: str, quantity: int) -> list[Item]:
    if not 1 <= quantity <= MAX_ITEMS_PER_ADD:
        raise ValueError("quantity must be between 1 and 20")
    size = normalize_size(size)
    items = []
    for _ in range(quantity):
        item = Item(
            shop_id=style.shop_id,
            style_id=style.id,
            size=size,
            code=new_item_code(session, style.shop_id),
        )
        session.add(item)
        session.flush()
        items.append(item)
    return items


from uuid import uuid4  # noqa: E402

from twirl.images import InvalidImage, process_image  # noqa: E402
from twirl.models import StyleImage  # noqa: E402
from twirl.storage import Storage  # noqa: E402

MAX_IMAGES_PER_STYLE = 8


def save_style_image(session: Session, storage: Storage, style: Style, data: bytes) -> StyleImage:
    count = (
        session.scalar(
            select(func.count()).select_from(StyleImage).where(StyleImage.style_id == style.id)
        )
        or 0
    )
    if count >= MAX_IMAGES_PER_STYLE:
        raise InvalidImage("too_many")
    processed = process_image(data)
    key = f"styles/{style.id}/{uuid4().hex}"
    for variant, blob in processed.variants.items():
        storage.put(f"{key}-{variant}.webp", blob, "image/webp")
    image = StyleImage(
        style_id=style.id,
        position=count,
        storage_key=key,
        width=processed.width,
        height=processed.height,
    )
    session.add(image)
    session.flush()
    return image


def image_url(storage: Storage, image: StyleImage, variant: str = "thumb") -> str:
    return storage.url(f"{image.storage_key}-{variant}.webp")
