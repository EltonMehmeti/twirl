import io
from datetime import date
from decimal import Decimal

import segno
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from twirl import clock
from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import ShopContext, require_owner, require_shop
from twirl.booking.errors import InvalidDates, ItemConflict
from twirl.booking.staff import create_block, set_item_status
from twirl.catalog import add_items, create_style, image_url, save_style_image, size_sort_key
from twirl.db import get_db
from twirl.i18n import N_
from twirl.images import MAX_UPLOAD_BYTES, InvalidImage
from twirl.models import ColourFamily, DressLength, Item, ItemStatus, Occasion, Style
from twirl.storage import Storage, get_storage
from twirl.web.forms import form_data, validate_form
from twirl.web.templating import render

router = APIRouter(prefix="/shop")

CHOICES = {
    "occasions": [
        (Occasion.WEDDING.value, N_("Wedding")),
        (Occasion.ENGAGEMENT.value, N_("Engagement")),
        (Occasion.MATURA.value, N_("Matura")),
        (Occasion.HENNA_NIGHT.value, N_("Henna night")),
        (Occasion.EVENING.value, N_("Evening")),
    ],
    "colours": [
        (ColourFamily.BLACK.value, N_("Black")),
        (ColourFamily.WHITE.value, N_("White")),
        (ColourFamily.RED.value, N_("Red")),
        (ColourFamily.PINK.value, N_("Pink")),
        (ColourFamily.BLUE.value, N_("Blue")),
        (ColourFamily.GREEN.value, N_("Green")),
        (ColourFamily.GOLD.value, N_("Gold")),
        (ColourFamily.SILVER.value, N_("Silver")),
        (ColourFamily.BEIGE.value, N_("Beige")),
        (ColourFamily.PURPLE.value, N_("Purple")),
        (ColourFamily.MULTI.value, N_("Multicolour")),
    ],
    "lengths": [
        (DressLength.MINI.value, N_("Short")),
        (DressLength.MIDI.value, N_("Midi")),
        (DressLength.MAXI.value, N_("Long")),
    ],
}
ITEM_STATUSES = [
    (ItemStatus.ACTIVE.value, N_("Available")),
    (ItemStatus.CLEANING.value, N_("Cleaning")),
    (ItemStatus.REPAIR.value, N_("Repair")),
    (ItemStatus.RETIRED.value, N_("Retired")),
    (ItemStatus.LOST.value, N_("Lost")),
]
PAGE_ERRORS = {
    "block_conflict": N_("That dress is already booked or blocked on those dates."),
    "block_dates": N_("The block end date must be on or after the start date."),
    "block_invalid": N_("Enter both dates and a reason for the block."),
    "future_bookings": N_("This dress still has upcoming bookings. Swap them to another dress."),
}
IMAGE_ERRORS = {
    "too_large": N_("That photo is larger than 15 MB."),
    "not_an_image": N_("That file is not a photo."),
    "unsupported_format": N_("Use JPEG, PNG or WebP photos."),
    "too_many": N_("A dress can have at most 8 photos."),
}


class StyleForm(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    price_eur: Decimal = Field(ge=0, le=5000, decimal_places=2)
    description: str = Field(default="", max_length=2000)
    occasion_tags: list[Occasion] = []
    colour_family: ColourFamily | None = None
    length: DressLength | None = None
    stretch: bool = False
    adjustable_back: bool = False
    published: bool = False

    @field_validator("price_eur", mode="before")
    @classmethod
    def _decimal_comma(cls, value):
        return value.replace(",", ".").strip() if isinstance(value, str) else value

    @field_validator("colour_family", "length", mode="before")
    @classmethod
    def _blank_is_none(cls, value):
        return value or None

    @field_validator("stretch", "adjustable_back", "published", mode="before")
    @classmethod
    def _checkbox(cls, value):
        return bool(value) and value not in ("off", "false", "0")

    @property
    def price_cents(self) -> int:
        return int(self.price_eur * 100)


class ItemsForm(BaseModel):
    size: str = Field(min_length=1, max_length=8)
    quantity: int = Field(ge=1, le=20)


class BlockForm(BaseModel):
    starts_on: date
    ends_on: date
    reason: str = Field(min_length=2, max_length=300)


def _get_style(db: Session, ctx: ShopContext, style_id: int) -> Style:
    style = db.get(Style, style_id)
    if style is None or style.shop_id != ctx.shop.id or style.deleted_at is not None:
        raise HTTPException(status_code=404)
    return style


def _get_item(db: Session, ctx: ShopContext, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None or item.shop_id != ctx.shop.id:
        raise HTTPException(status_code=404)
    return item


def _style_values(style: Style) -> dict:
    return {
        "name": style.name,
        "price_eur": f"{style.price_cents / 100:.2f}",
        "description": style.description,
        "occasion_tags": list(style.occasion_tags),
        "colour_family": style.colour_family or "",
        "length": style.length or "",
        "stretch": style.stretch,
        "adjustable_back": style.adjustable_back,
        "published": style.published,
    }


def _form_values(form: FormData) -> dict:
    return {
        "name": form.get("name", ""),
        "price_eur": form.get("price_eur", ""),
        "description": form.get("description", ""),
        "occasion_tags": form.getlist("occasion_tags"),
        "colour_family": form.get("colour_family", ""),
        "length": form.get("length", ""),
        "stretch": bool(form.get("stretch")),
        "adjustable_back": bool(form.get("adjustable_back")),
        "published": bool(form.get("published")),
    }


def _style_page(
    request: Request,
    ctx: ShopContext,
    style: Style,
    storage: Storage,
    *,
    values: dict | None = None,
    errors: dict | None = None,
    error: str | None = None,
    status_code: int = 200,
):
    return render(
        request,
        "shop/style_edit.html",
        {
            "ctx": ctx,
            "style": style,
            "items": sorted(style.items, key=lambda i: (size_sort_key(i.size), i.code)),
            "images": [image_url(storage, image) for image in style.images],
            "values": values or _style_values(style),
            "errors": errors or {},
            "error": error,
            "choices": CHOICES,
            "item_statuses": ITEM_STATUSES,
        },
        status_code=status_code,
    )


def _apply(style_kwargs: StyleForm) -> dict:
    return {
        "name": style_kwargs.name.strip(),
        "price_cents": style_kwargs.price_cents,
        "description": style_kwargs.description.strip(),
        "occasion_tags": [tag.value for tag in style_kwargs.occasion_tags],
        "colour_family": style_kwargs.colour_family.value if style_kwargs.colour_family else None,
        "length": style_kwargs.length.value if style_kwargs.length else None,
        "stretch": style_kwargs.stretch,
        "adjustable_back": style_kwargs.adjustable_back,
        "published": style_kwargs.published,
    }


@router.get("/styles", response_class=HTMLResponse)
def list_styles(
    request: Request,
    ctx: ShopContext = Depends(require_shop),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    styles = db.scalars(
        select(Style)
        .where(Style.shop_id == ctx.shop.id, Style.deleted_at.is_(None))
        .order_by(Style.code)
    ).all()
    rows = [
        {
            "style": s,
            "thumb": image_url(storage, s.images[0]) if s.images else None,
            "pieces": len(s.items),
        }
        for s in styles
    ]
    return render(request, "shop/styles.html", {"ctx": ctx, "rows": rows})


@router.get("/styles/new", response_class=HTMLResponse)
def new_style_form(request: Request, ctx: ShopContext = Depends(require_owner)):
    values = {
        "name": "",
        "price_eur": "",
        "description": "",
        "occasion_tags": [],
        "colour_family": "",
        "length": "",
        "stretch": False,
        "adjustable_back": False,
        "published": True,
    }
    return render(
        request,
        "shop/style_new.html",
        {"ctx": ctx, "values": values, "errors": {}, "choices": CHOICES},
    )


@router.post("/styles/new", dependencies=[Depends(verify_csrf)])
def create_style_route(
    request: Request,
    form: FormData = Depends(form_data),
    ctx: ShopContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    parsed, errors = validate_form(StyleForm, form, list_fields=("occasion_tags",))
    if parsed is None:
        return render(
            request,
            "shop/style_new.html",
            {"ctx": ctx, "values": _form_values(form), "errors": errors, "choices": CHOICES},
            status_code=400,
        )
    style = create_style(db, ctx.shop, **_apply(parsed))
    db.commit()
    return RedirectResponse(f"/shop/styles/{style.id}", status_code=303)


@router.get("/styles/{style_id}", response_class=HTMLResponse)
def style_page(
    request: Request,
    style_id: int,
    error: str | None = None,
    ctx: ShopContext = Depends(require_shop),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    style = _get_style(db, ctx, style_id)
    return _style_page(request, ctx, style, storage, error=PAGE_ERRORS.get(error or ""))


@router.post("/styles/{style_id}", dependencies=[Depends(verify_csrf)])
def update_style(
    request: Request,
    style_id: int,
    form: FormData = Depends(form_data),
    ctx: ShopContext = Depends(require_owner),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    style = _get_style(db, ctx, style_id)
    parsed, errors = validate_form(StyleForm, form, list_fields=("occasion_tags",))
    if parsed is None:
        return _style_page(
            request, ctx, style, storage, values=_form_values(form), errors=errors, status_code=400
        )
    for field, value in _apply(parsed).items():
        setattr(style, field, value)
    db.commit()
    return RedirectResponse(f"/shop/styles/{style.id}", status_code=303)


@router.post("/styles/{style_id}/images", dependencies=[Depends(verify_csrf)])
def upload_images(
    request: Request,
    style_id: int,
    files: list[UploadFile] = File(...),
    ctx: ShopContext = Depends(require_shop),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    style = _get_style(db, ctx, style_id)
    failures = []
    for upload in files:
        try:
            save_style_image(db, storage, style, upload.file.read(MAX_UPLOAD_BYTES + 1))
        except InvalidImage as exc:
            failures.append(IMAGE_ERRORS.get(exc.code, IMAGE_ERRORS["not_an_image"]))
    db.commit()
    if failures:
        db.refresh(style)
        return _style_page(request, ctx, style, storage, error=failures[0], status_code=400)
    return RedirectResponse(f"/shop/styles/{style.id}", status_code=303)


@router.post("/styles/{style_id}/items", dependencies=[Depends(verify_csrf)])
def add_items_route(
    request: Request,
    style_id: int,
    form: FormData = Depends(form_data),
    ctx: ShopContext = Depends(require_shop),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    style = _get_style(db, ctx, style_id)
    parsed, _ = validate_form(ItemsForm, form)
    if parsed is None:
        return _style_page(
            request,
            ctx,
            style,
            storage,
            error=N_("Enter a size and a quantity from 1 to 20."),
            status_code=400,
        )
    add_items(db, style, size=parsed.size, quantity=parsed.quantity)
    db.commit()
    return RedirectResponse(f"/shop/styles/{style.id}", status_code=303)


@router.post("/items/{item_id}/status", dependencies=[Depends(verify_csrf)])
def item_status(
    item_id: int,
    form: FormData = Depends(form_data),
    ctx: ShopContext = Depends(require_shop),
    db: Session = Depends(get_db),
):
    item = _get_item(db, ctx, item_id)
    try:
        future = set_item_status(
            db, item, str(form.get("status", "")), actor=ctx.actor, today=clock.today()
        )
    except ValueError as exc:
        raise HTTPException(status_code=400) from exc
    db.commit()
    suffix = "?error=future_bookings" if future and item.status != ItemStatus.ACTIVE.value else ""
    return RedirectResponse(f"/shop/styles/{item.style_id}{suffix}", status_code=303)


@router.post("/items/{item_id}/block", dependencies=[Depends(verify_csrf)])
def block_item(
    item_id: int,
    form: FormData = Depends(form_data),
    ctx: ShopContext = Depends(require_shop),
    db: Session = Depends(get_db),
):
    item = _get_item(db, ctx, item_id)
    target = f"/shop/styles/{item.style_id}"
    parsed, _ = validate_form(BlockForm, form)
    if parsed is None:
        return RedirectResponse(f"{target}?error=block_invalid", status_code=303)
    try:
        create_block(
            db,
            item=item,
            starts_on=parsed.starts_on,
            ends_on=parsed.ends_on,
            reason=parsed.reason,
            actor=ctx.actor,
        )
    except ItemConflict:
        db.rollback()
        return RedirectResponse(f"{target}?error=block_conflict", status_code=303)
    except InvalidDates:
        db.rollback()
        return RedirectResponse(f"{target}?error=block_dates", status_code=303)
    db.commit()
    return RedirectResponse(target, status_code=303)


@router.get("/items/{item_id}/qr.svg")
def item_qr(
    request: Request,
    item_id: int,
    ctx: ShopContext = Depends(require_shop),
    db: Session = Depends(get_db),
):
    item = _get_item(db, ctx, item_id)
    url = f"{request.app.state.settings.base_url}/shop/walk-in?code={item.code}"
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="svg", scale=4)
    return Response(buffer.getvalue(), media_type="image/svg+xml")
