from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from twirl import clock
from twirl.auth.csrf import verify_csrf
from twirl.booking.availability import style_availability
from twirl.booking.errors import InvalidDates, NoAvailability, ShopNotBookable
from twirl.booking.requests import RentalRequest, create_request
from twirl.catalog import image_url, size_sort_key
from twirl.db import get_db
from twirl.i18n import N_
from twirl.models import Booking, BookingKind, Item, ItemStatus, Shop, ShopStatus, Style
from twirl.phones import InvalidPhone
from twirl.ratelimit import client_ip
from twirl.storage import Storage, get_storage
from twirl.web.forms import form_data, validate_form
from twirl.web.messages import DATE_ERRORS, GENERIC_DATE_ERROR
from twirl.web.templating import render

router = APIRouter()

RENTER_STATUS = {
    "pending_shop": N_("The shop will confirm your request within 24 hours."),
    "confirmed": N_("The shop has confirmed your booking."),
}
CLOSED_STATUS = N_("This request is closed. Contact the shop for details.")


class RequestForm(BaseModel):
    event_date: date
    size: str = Field(min_length=1, max_length=8)
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=30)
    note: str = Field(default="", max_length=500)


def _shop(db: Session, slug: str) -> Shop:
    shop = db.scalar(
        select(Shop).where(Shop.slug == slug, Shop.status == ShopStatus.PUBLISHED.value)
    )
    if shop is None:
        raise HTTPException(status_code=404)
    return shop


def _style(db: Session, shop: Shop, code: str) -> Style:
    style = db.scalar(
        select(Style).where(
            Style.shop_id == shop.id,
            Style.code == code,
            Style.published.is_(True),
            Style.deleted_at.is_(None),
        )
    )
    if style is None:
        raise HTTPException(status_code=404)
    return style


def _style_context(
    request: Request, db: Session, storage: Storage, shop: Shop, style: Style
) -> dict:
    sizes = sorted(
        set(
            db.scalars(
                select(Item.size).where(
                    Item.style_id == style.id, Item.status == ItemStatus.ACTIVE.value
                )
            )
        ),
        key=size_sort_key,
    )
    images = [
        {"thumb": image_url(storage, i, "thumb"), "detail": image_url(storage, i, "detail")}
        for i in style.images
    ]
    base_url = request.app.state.settings.base_url
    return {
        "shop": shop,
        "style": style,
        "sizes": sizes,
        "images": images,
        "og_image": f"{base_url}{images[0]['detail']}" if images else None,
        "min_date": (clock.today() + timedelta(days=1)).isoformat(),
    }


@router.get("/{slug}", response_class=HTMLResponse)
def shop_page(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    shop = _shop(db, slug)
    styles = db.scalars(
        select(Style)
        .where(Style.shop_id == shop.id, Style.published.is_(True), Style.deleted_at.is_(None))
        .order_by(Style.created_at.desc())
    ).all()
    cards = [
        {"style": s, "thumb": image_url(storage, s.images[0]) if s.images else None} for s in styles
    ]
    return render(request, "storefront/shop.html", {"shop": shop, "cards": cards})


@router.get("/{slug}/r/{ref}", response_class=HTMLResponse)
def confirmation(request: Request, slug: str, ref: str, db: Session = Depends(get_db)):
    shop = _shop(db, slug)
    booking = db.scalar(
        select(Booking).where(
            Booking.shop_id == shop.id, Booking.ref == ref, Booking.kind == BookingKind.ONLINE.value
        )
    )
    if booking is None:
        raise HTTPException(status_code=404)
    text = quote(f"Përshëndetje! Kam një kërkesë në Vesha me kodin {booking.ref}.")
    return render(
        request,
        "storefront/confirmation.html",
        {
            "shop": shop,
            "booking": booking,
            "status_text": RENTER_STATUS.get(booking.status, CLOSED_STATUS),
            "whatsapp_url": f"https://wa.me/{shop.whatsapp.lstrip('+')}?text={text}"
            if shop.whatsapp
            else None,
            "viber_url": f"viber://chat?number={quote(shop.viber)}" if shop.viber else None,
        },
    )


@router.get("/{slug}/{code}", response_class=HTMLResponse)
def style_page(
    request: Request,
    slug: str,
    code: str,
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    shop = _shop(db, slug)
    style = _style(db, shop, code)
    context = _style_context(request, db, storage, shop, style)
    return render(request, "storefront/style.html", {**context, "values": {}, "error": None})


@router.get("/{slug}/{code}/availability", response_class=HTMLResponse)
def availability(
    request: Request,
    slug: str,
    code: str,
    event_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    shop = _shop(db, slug)
    style = _style(db, shop, code)
    context = {"availability": None, "error": None}
    if event_date is not None:
        try:
            context["availability"] = style_availability(db, style, event_date, today=clock.today())
        except InvalidDates as exc:
            context["error"] = DATE_ERRORS.get(exc.code, GENERIC_DATE_ERROR)
    return render(request, "storefront/_availability.html", context)


@router.post("/{slug}/{code}/request", dependencies=[Depends(verify_csrf)])
def request_dress(
    request: Request,
    slug: str,
    code: str,
    form: FormData = Depends(form_data),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    shop = _shop(db, slug)
    style = _style(db, shop, code)
    settings = request.app.state.settings
    values = {
        key: str(form.get(key) or "") for key in ("event_date", "size", "name", "phone", "note")
    }

    def page(error: str, status_code: int = 400):
        context = _style_context(request, db, storage, shop, style)
        return render(
            request,
            "storefront/style.html",
            {**context, "values": values, "error": error},
            status_code=status_code,
        )

    if form.get("website"):
        return RedirectResponse(f"/{shop.slug}", status_code=303)
    if not request.app.state.request_limiter.allow(
        client_ip(request, trust_cf=settings.trust_cf_connecting_ip)
    ):
        return page(N_("Too many requests from your connection. Try again later."), 429)
    parsed, _ = validate_form(RequestForm, form)
    if parsed is None:
        return page(N_("Please fill in your event date, size, name and phone."))
    try:
        booking = create_request(
            db,
            RentalRequest(
                style_id=style.id,
                size=parsed.size,
                event_date=parsed.event_date,
                name=parsed.name,
                phone=parsed.phone,
                note=parsed.note,
            ),
            today=clock.today(),
        )
    except InvalidPhone:
        db.rollback()
        return page(N_("That phone number does not look right."))
    except InvalidDates as exc:
        db.rollback()
        return page(DATE_ERRORS.get(exc.code, GENERIC_DATE_ERROR))
    except NoAvailability:
        db.rollback()
        return page(
            N_("Sorry, that size is not free for your date. Try another size or date."), 409
        )
    except ShopNotBookable as exc:
        db.rollback()
        raise HTTPException(status_code=404) from exc
    db.commit()
    return RedirectResponse(f"/{shop.slug}/r/{booking.ref}", status_code=303)
