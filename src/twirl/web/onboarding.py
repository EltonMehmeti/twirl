"""Provider onboarding wizard at /listo, following docs/design/Provider Onboarding.dc.html.

State lives in the database (draft shop, draft style, photos, blocks). The session only
remembers the chosen path, the phone waiting for its code and the draft style id. Every step
checks how far the provider has really got and redirects forward or back as needed.
"""

from dataclasses import dataclass
from datetime import date, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from twirl import clock
from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import SESSION_USER_KEY, login_user
from twirl.booking.actor import Actor
from twirl.catalog import delete_style_image, image_url, save_style_image
from twirl.db import get_db
from twirl.i18n import MONTHS, N_
from twirl.images import MAX_UPLOAD_BYTES, InvalidImage
from twirl.models import ActorKind, ItemStatus, Shop, ShopKind, Style, StyleImage, User
from twirl.onboarding import (
    CITIES,
    CUSTOM_SIZE,
    MAX_PHOTOS,
    MIN_PHOTOS,
    SIZES,
    OnboardingError,
    WeeklyHours,
    active_items,
    blocked_dates,
    dress_errors,
    get_or_create_draft_style,
    month_grid,
    next_months,
    photo_count,
    provider_errors,
    provider_shop,
    publish,
    save_provider,
    set_dress,
    set_price_and_dates,
    verify_provider_phone,
    weekly_hours,
)
from twirl.otp import OtpError, TooMany, verify_code
from twirl.phones import InvalidPhone, normalize_phone
from twirl.storage import Storage, get_storage
from twirl.web.forms import form_data
from twirl.web.phone_auth import SESSION_ECHO, display_phone, resend_wait, send_code
from twirl.web.templating import format_money, render

router = APIRouter(prefix="/listo")

SESSION_PATH = "onb_path"
SESSION_PHONE = "onb_phone"
SESSION_STYLE = "onb_style"
PATHS = {"salon": ShopKind.SALON, "individual": ShopKind.INDIVIDUAL}

STEPS = ["fork", "phone", "code", "profile", "dress", "price", "review", "done"]
URLS = {
    "fork": "/listo",
    "phone": "/listo/telefoni",
    "code": "/listo/kodi",
    "profile": "/listo/profili",
    "dress": "/listo/veshja",
    "price": "/listo/cmimi",
    "review": "/listo/permbledhja",
    "done": "/listo/gati",
}
RAIL_KEYS = ["phone", "profile", "dress", "price", "review"]

CATEGORY_LABELS = [
    ("evening", N_("Evening")),
    ("bridal", N_("Bridal")),
    ("engagement", N_("Engagement")),
    ("mens_suit", N_("Men's suit")),
    ("traditional", N_("Traditional")),
]
CATEGORY_LABEL = dict(CATEGORY_LABELS)
PHOTO_LABELS = [N_("Front"), N_("Side"), N_("Detail")]
WEEKDAY_SHORT = [N_("Mon"), N_("Tue"), N_("Wed"), N_("Thu"), N_("Fri"), N_("Sat"), N_("Sun")]

ERRORS = {
    "phone": N_("Write the number like 044 123 456."),
    "code": N_("That code is not right or has expired."),
    "name": N_("Write your first and last name."),
    "salon_name": N_("Write the name as it appears on your sign."),
    "address": N_("Write the street and number."),
    "city": N_("Choose the city."),
    "whatsapp": N_("Write the WhatsApp number like 044 123 456."),
    "hours": N_("Closing time must be after opening time."),
    "photos": N_("Add at least 3 photos: front, side and a detail."),
    "category": N_("Choose a category."),
    "sizes": N_("Choose the size."),
    "sizes_salon": N_("Choose at least one size."),
    "price": N_("Write the rent in euros, digits only, from 5 to 2000."),
    "terms": N_("Confirm the promise before publishing."),
}


def size_label(size: str) -> str:
    return N_("Made to measure") if size == CUSTOM_SIZE else size


# ── flow state ─────────────────────────────────────────────────────────


@dataclass
class Flow:
    path: ShopKind | None
    user: User | None
    shop: Shop | None
    style: Style | None
    pending_phone: str | None

    @property
    def is_salon(self) -> bool:
        return self.path == ShopKind.SALON

    def reached(self) -> str:
        """The furthest step this provider may open right now."""
        if self.user is None:
            if self.path is None:
                return "fork"
            return "code" if self.pending_phone else "phone"
        if self.shop is None:
            return "profile" if self.path else "fork"
        style = self.style
        if style is not None and style.published:
            return "done"
        if style is None or style.category is None or not active_items(style):
            return "dress"
        if style.price_cents <= 0:
            return "price"
        return "review"


def _flow(request: Request, db: Session) -> Flow:
    user = None
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None and user.blocked_at is not None:
            user = None
    shop = provider_shop(db, user) if user else None
    path = PATHS.get(request.session.get(SESSION_PATH, ""))
    if shop is not None:
        path = ShopKind(shop.kind)
    style = None
    style_id = request.session.get(SESSION_STYLE)
    if shop is not None and style_id:
        candidate = db.get(Style, style_id)
        if candidate is not None and candidate.shop_id == shop.id and candidate.deleted_at is None:
            style = candidate
    return Flow(
        path=path,
        user=user,
        shop=shop,
        style=style,
        pending_phone=request.session.get(SESSION_PHONE),
    )


def _guard(flow: Flow, step: str) -> RedirectResponse | None:
    reached = flow.reached()
    if STEPS.index(step) > STEPS.index(reached):
        return RedirectResponse(URLS[reached], status_code=303)
    return None


def _go(step: str) -> RedirectResponse:
    return RedirectResponse(URLS[step], status_code=303)


def _page(
    request: Request,
    flow: Flow,
    step: str,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
):
    salon = flow.is_salon
    rail_labels = {
        "phone": N_("Phone number"),
        "profile": N_("Salon and hours") if salon else N_("Profile"),
        "dress": N_("First item"),
        "price": N_("Price and dates"),
        "review": N_("Publishing"),
    }
    rail_key = "phone" if step in ("phone", "code") else step
    total = len(RAIL_KEYS)
    active = (
        RAIL_KEYS.index(rail_key) if rail_key in RAIL_KEYS else (total if step == "done" else -1)
    )
    rail = [
        {
            "num": f"{i + 1:02d}",
            "label": rail_labels[key],
            "state": "done"
            if (step == "done" or i < active)
            else ("now" if i == active else "todo"),
        }
        for i, key in enumerate(RAIL_KEYS)
    ]
    in_steps = step not in ("fork", "done")
    shown = active + 1 if active >= 0 else 0
    base = {
        "flow": flow,
        "step": step,
        "is_salon": salon,
        "rail": rail if in_steps else None,
        "rail_note_label": N_("How renters pay"),
        "rail_note": (
            N_("Customers pay in the salon, as they do today. Online payment comes later.")
            if salon
            else N_(
                "The renter pays you when they pick the item up. Vesha takes no payment for now."
            )
        ),
        "show_progress": in_steps,
        "progress": round(shown / total * 100),
        "counter": _counter(step, shown, total),
        "path_label": N_("Salon or business") if salon else N_("My own clothes"),
        "path_footer": (
            N_("Path: salon · paid in the salon")
            if salon
            else N_("Path: individual · paid at handover")
        )
        if flow.path
        else None,
        "errors": {},
    }
    return render(request, template, {**base, **(context or {})}, status_code=status_code)


def _counter(step: str, shown: int, total: int) -> dict:
    if step == "done":
        return {"text": N_("Published"), "n": "", "total": ""}
    return {"text": N_("Step {n} / {total}"), "n": str(shown), "total": str(total)}


def _errors(codes: list[str], salon: bool = False) -> dict[str, str]:
    out = {}
    for code in codes:
        key = "sizes_salon" if code == "sizes" and salon else code
        out[code] = ERRORS[key]
    return out


# ── fork ───────────────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse)
def fork(request: Request, db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if flow.user is not None and flow.shop is not None:
        return _go("dress")
    return _page(request, flow, "fork", "onboarding/fork.html")


@router.post("", dependencies=[Depends(verify_csrf)])
def choose_path(request: Request, path: str = Form(""), db: Session = Depends(get_db)):
    if path not in PATHS:
        raise HTTPException(status_code=400)
    request.session[SESSION_PATH] = path
    flow = _flow(request, db)
    return _go("profile" if flow.user is not None else "phone")


# ── phone and code ─────────────────────────────────────────────────────


def _phone_context(
    flow: Flow, phone: str = "", errors: dict | None = None, error: str | None = None
) -> dict:
    return {
        "action": URLS["phone"],
        "eyebrow": N_("Salon or business") if flow.is_salon else N_("My own clothes"),
        "lede": (
            N_(
                "The salon owner's number. The salon's WhatsApp is added separately in the next step."  # noqa: E501
            )
            if flow.is_salon
            else N_("A verified number is the only check needed to list an item.")
        ),
        "back_url": URLS["fork"],
        "phone": phone,
        "errors": errors or {},
        "error": error,
    }


@router.get("/telefoni", response_class=HTMLResponse)
def phone_page(request: Request, db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if flow.path is None:
        return _go("fork")
    if flow.user is not None:
        return _go("profile")
    shown = display_phone(flow.pending_phone) if flow.pending_phone else ""
    return _page(request, flow, "phone", "auth/phone.html", _phone_context(flow, shown))


@router.post("/telefoni", dependencies=[Depends(verify_csrf)])
def phone_submit(request: Request, phone: str = Form(""), db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if flow.path is None:
        return _go("fork")
    try:
        e164 = normalize_phone(phone)
    except InvalidPhone:
        return _page(
            request,
            flow,
            "phone",
            "auth/phone.html",
            _phone_context(flow, phone, {"phone": ERRORS["phone"]}),
            status_code=400,
        )
    try:
        send_code(request, db, e164, "signup")
    except TooMany:
        message = N_("Too many codes for this number. Try again in an hour.")
        return _page(
            request,
            flow,
            "phone",
            "auth/phone.html",
            _phone_context(flow, phone, error=message),
            status_code=429,
        )
    except OtpError:
        pass  # sent moments ago; the code screen shows how long to wait
    request.session[SESSION_PHONE] = e164
    db.commit()
    return _go("code")


def _code_context(request: Request, db: Session, flow: Flow, errors: dict | None = None) -> dict:
    return {
        "action": URLS["code"],
        "resend_action": URLS["code"] + "/perseri",
        "change_url": URLS["phone"],
        "eyebrow": N_("Salon or business") if flow.is_salon else N_("My own clothes"),
        "phone_display": display_phone(flow.pending_phone or ""),
        "resend_in": resend_wait(db, flow.pending_phone or ""),
        "echo": request.session.get(SESSION_ECHO),
        "errors": errors or {},
    }


@router.get("/kodi", response_class=HTMLResponse)
def code_page(request: Request, db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if flow.user is not None:
        return _go("profile")
    if redirect := _guard(flow, "code"):
        return redirect
    return _page(request, flow, "code", "auth/code.html", _code_context(request, db, flow))


@router.post("/kodi/perseri", dependencies=[Depends(verify_csrf)])
def code_resend(request: Request, db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if flow.pending_phone and flow.user is None:
        try:
            send_code(request, db, flow.pending_phone, "signup")
            db.commit()
        except OtpError:
            pass
    return _go("code")


@router.post("/kodi", dependencies=[Depends(verify_csrf)])
def code_submit(request: Request, code: str = Form(""), db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if flow.user is not None:
        return _go("profile")
    if redirect := _guard(flow, "code"):
        return redirect
    settings = request.app.state.settings
    phone = flow.pending_phone or ""
    ok = verify_code(
        db, phone=phone, purpose="signup", code=code, now=clock.now(), secret=settings.secret_key
    )
    if not ok:
        db.commit()  # keep the attempt count
        return _page(
            request,
            flow,
            "code",
            "auth/code.html",
            _code_context(request, db, flow, {"code": ERRORS["code"]}),
            status_code=400,
        )
    user = verify_provider_phone(db, phone=phone, now=clock.now())
    path = request.session.get(SESSION_PATH)
    db.commit()
    login_user(request, user)  # clears the session, so restore the chosen path
    if path:
        request.session[SESSION_PATH] = path
    return _go("dress" if provider_shop(db, user) else "profile")


# ── profile (individual) or salon ──────────────────────────────────────


def _parse_time(value: str, fallback: time) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError:
        return fallback


def _profile_values(flow: Flow) -> dict:
    shop = flow.shop
    hours = weekly_hours(shop) if shop else weekly_hours(Shop())
    return {
        "name": shop.name if shop else "",
        "city": shop.city if shop else "",
        "address": shop.address if shop else "",
        "whatsapp": display_phone(shop.whatsapp) if shop and shop.whatsapp else "",
        "wd_open": hours.weekday_open.strftime("%H:%M"),
        "wd_close": hours.weekday_close.strftime("%H:%M"),
        "sat_open": hours.saturday_open.strftime("%H:%M"),
        "sat_close": hours.saturday_close.strftime("%H:%M"),
        "sunday": "closed" if hours.sunday_closed else "open",
    }


def _profile_page(request, flow, values, errors=None, status_code=200):
    return _page(
        request,
        flow,
        "profile",
        "onboarding/profile.html",
        {"values": values, "errors": errors or {}, "cities": CITIES},
        status_code=status_code,
    )


@router.get("/profili", response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if redirect := _guard(flow, "profile"):
        return redirect
    return _profile_page(request, flow, _profile_values(flow))


@router.post("/profili", dependencies=[Depends(verify_csrf)])
def profile_submit(
    request: Request, form: FormData = Depends(form_data), db: Session = Depends(get_db)
):
    flow = _flow(request, db)
    if redirect := _guard(flow, "profile"):
        return redirect
    kind = flow.path
    keys = (
        "name",
        "city",
        "address",
        "whatsapp",
        "wd_open",
        "wd_close",
        "sat_open",
        "sat_close",
        "sunday",
    )
    values = {key: str(form.get(key) or "") for key in keys}
    hours = WeeklyHours(
        _parse_time(values["wd_open"], time(9)),
        _parse_time(values["wd_close"], time(20)),
        _parse_time(values["sat_open"], time(9)),
        _parse_time(values["sat_close"], time(18)),
        sunday_closed=values["sunday"] != "open",
    )
    codes = provider_errors(
        kind,
        name=values["name"],
        city=values["city"],
        address=values["address"],
        whatsapp=values["whatsapp"],
        hours=hours,
    )
    if codes:
        return _profile_page(request, flow, values, _errors(codes), status_code=400)
    save_provider(
        db,
        user=flow.user,
        kind=kind,
        name=values["name"],
        city=values["city"],
        address=values["address"],
        whatsapp=values["whatsapp"],
        hours=hours,
    )
    db.commit()
    return _go("dress")


# ── the first item ─────────────────────────────────────────────────────


def _photo_slots(db: Session, storage: Storage, style: Style) -> list[dict]:
    images = sorted(style.images, key=lambda i: i.position)
    slots = [
        {
            "image": image,
            "url": image_url(storage, image),
            "label": PHOTO_LABELS[i] if i < len(PHOTO_LABELS) else N_("Extra"),
        }
        for i, image in enumerate(images)
    ]
    empty = max(0, max(4, len(images) + 1) - len(images))
    if len(images) >= MAX_PHOTOS:
        empty = 0
    for i in range(len(images), len(images) + empty):
        slots.append(
            {
                "image": None,
                "url": None,
                "label": PHOTO_LABELS[i] if i < len(PHOTO_LABELS) else N_("Add"),
            }
        )
    return slots


def _photos_partial(request, db, storage, style, errors=None, status_code=200):
    return render(
        request,
        "onboarding/_photos.html",
        {
            "photo_slots": _photo_slots(db, storage, style),
            "errors": errors or {},
            "min_photos": MIN_PHOTOS,
        },
        status_code=status_code,
    )


def _dress_values(style: Style) -> dict:
    return {
        "category": style.category or "",
        "sizes": [item.size for item in active_items(style)],
        "description": style.description or "",
        "internal_ref": style.internal_ref or "",
    }


def _dress_page(request, db, storage, flow, values, errors=None, status_code=200):
    return _page(
        request,
        flow,
        "dress",
        "onboarding/dress.html",
        {
            "values": values,
            "errors": errors or {},
            "photo_slots": _photo_slots(db, storage, flow.style),
            "min_photos": MIN_PHOTOS,
            "categories": CATEGORY_LABELS,
            "sizes": [(size, size_label(size)) for size in SIZES],
        },
        status_code=status_code,
    )


@router.get("/veshja", response_class=HTMLResponse)
def dress_page(
    request: Request, db: Session = Depends(get_db), storage: Storage = Depends(get_storage)
):
    flow = _flow(request, db)
    if redirect := _guard(flow, "dress"):
        return redirect
    if flow.style is None or flow.style.published:
        flow.style = get_or_create_draft_style(db, flow.shop, None)
        request.session[SESSION_STYLE] = flow.style.id
        db.commit()
    return _dress_page(request, db, storage, flow, _dress_values(flow.style))


def _draft_style_or_404(flow: Flow) -> Style:
    if flow.shop is None or flow.style is None or flow.style.published:
        raise HTTPException(status_code=404)
    return flow.style


@router.post("/veshja/foto", dependencies=[Depends(verify_csrf)])
def photo_upload(
    request: Request,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    flow = _flow(request, db)
    style = _draft_style_or_404(flow)
    messages = {
        "too_large": N_("That photo is larger than 15 MB."),
        "not_an_image": N_("That file is not a photo."),
        "unsupported_format": N_("Use JPEG, PNG or WebP photos."),
        "too_many": N_("A dress can have at most 8 photos."),
    }
    try:
        save_style_image(db, storage, style, photo.file.read(MAX_UPLOAD_BYTES + 1))
    except InvalidImage as exc:
        db.rollback()
        db.refresh(style)
        return _photos_partial(
            request,
            db,
            storage,
            style,
            {"photos": messages.get(exc.code, messages["not_an_image"])},
            status_code=400,
        )
    db.commit()
    db.refresh(style)
    return _photos_partial(request, db, storage, style)


@router.post("/veshja/foto/{image_id}/fshi", dependencies=[Depends(verify_csrf)])
def photo_delete(
    request: Request,
    image_id: int,
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    flow = _flow(request, db)
    style = _draft_style_or_404(flow)
    image = db.get(StyleImage, image_id)
    if image is None or image.style_id != style.id:
        raise HTTPException(status_code=404)
    delete_style_image(db, storage, image)
    db.commit()
    db.refresh(style)
    return _photos_partial(request, db, storage, style)


@router.post("/veshja", dependencies=[Depends(verify_csrf)])
def dress_submit(
    request: Request,
    form: FormData = Depends(form_data),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    flow = _flow(request, db)
    if redirect := _guard(flow, "dress"):
        return redirect
    style = _draft_style_or_404(flow)
    values = {
        "category": str(form.get("category") or ""),
        "sizes": [str(s) for s in form.getlist("sizes")],
        "description": str(form.get("description") or ""),
        "internal_ref": str(form.get("internal_ref") or ""),
    }
    codes = dress_errors(db, style, flow.path, category=values["category"], sizes=values["sizes"])
    if codes:
        return _dress_page(
            request, db, storage, flow, values, _errors(codes, flow.is_salon), status_code=400
        )
    set_dress(
        db,
        style,
        kind=flow.path,
        category=values["category"],
        sizes=values["sizes"],
        description=values["description"],
        internal_ref=values["internal_ref"],
    )
    db.commit()
    return _go("price")


@router.post("/veshja/e-re", dependencies=[Depends(verify_csrf)])
def new_dress(request: Request):
    request.session.pop(SESSION_STYLE, None)
    return _go("dress")


# ── price and busy dates ───────────────────────────────────────────────


def _calendar(today: date, busy: set[date]) -> list[dict]:
    months = []
    for year, month in next_months(today, 2):
        cells = [
            None
            if day is None
            else {"date": day, "busy": day in busy, "past": day < today, "iso": day.isoformat()}
            for day in month_grid(year, month)
        ]
        months.append({"label": MONTHS[month - 1], "year": year, "cells": cells})
    return months


def _price_page(request, flow, db, price_value, busy, errors=None, status_code=200):
    return _page(
        request,
        flow,
        "price",
        "onboarding/price.html",
        {
            "price": price_value,
            "months": _calendar(clock.today(), busy),
            "weekdays": WEEKDAY_SHORT,
            "busy_count": len(busy),
            "errors": errors or {},
        },
        status_code=status_code,
    )


@router.get("/cmimi", response_class=HTMLResponse)
def price_page(request: Request, db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if redirect := _guard(flow, "price"):
        return redirect
    style = _draft_style_or_404(flow)
    price = str(style.price_cents // 100) if style.price_cents else ""
    return _price_page(request, flow, db, price, blocked_dates(db, style))


@router.post("/cmimi", dependencies=[Depends(verify_csrf)])
def price_submit(
    request: Request, form: FormData = Depends(form_data), db: Session = Depends(get_db)
):
    flow = _flow(request, db)
    if redirect := _guard(flow, "price"):
        return redirect
    style = _draft_style_or_404(flow)
    raw = str(form.get("price") or "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    busy = set()
    for value in form.getlist("busy"):
        try:
            busy.add(date.fromisoformat(str(value)))
        except ValueError:
            continue
    try:
        set_price_and_dates(
            db,
            style,
            price_eur=int(digits or 0),
            blocked=busy,
            actor=Actor(ActorKind.SHOP, flow.user.id),
            today=clock.today(),
        )
    except OnboardingError:
        db.rollback()
        return _price_page(
            request, flow, db, raw, busy, {"price": ERRORS["price"]}, status_code=400
        )
    db.commit()
    return _go("review")


# ── review, publish, done ──────────────────────────────────────────────


def _review_rows(request: Request, db: Session, flow: Flow) -> list[dict]:
    shop, style = flow.shop, flow.style
    locale_money = format_money(style.price_cents, "sq")
    sizes = ", ".join(size_label(item.size) for item in active_items(style))
    busy = sorted(blocked_dates(db, style))
    rows = [
        {"key": N_("Salon") if flow.is_salon else N_("Owner"), "value": shop.name},
    ]
    if flow.is_salon:
        hours = weekly_hours(shop)
        rows.append({"key": N_("Address"), "value": f"{shop.address}, {shop.city}"})
        rows.append(
            {
                "key": N_("Hours"),
                "hours": hours,
                "mono": True,
            }
        )
        rows.append(
            {"key": N_("WhatsApp"), "value": display_phone(shop.whatsapp or ""), "mono": True}
        )
    else:
        rows.append({"key": N_("City"), "value": shop.city})
        rows.append(
            {
                "key": N_("Phone"),
                "value": display_phone(flow.user.phone or ""),
                "verified": True,
                "mono": True,
            }
        )
    rows.append(
        {
            "key": N_("Item"),
            "category": CATEGORY_LABEL.get(style.category or "", ""),
            "value": sizes + (f" · {style.internal_ref}" if style.internal_ref else ""),
        }
    )
    rows.append({"key": N_("Photos"), "value": str(photo_count(db, style)), "mono": True})
    rows.append({"key": N_("Rent"), "value": locale_money, "mono": True})
    rows.append({"key": N_("Busy dates"), "busy": busy, "mono": True})
    return rows


@router.get("/permbledhja", response_class=HTMLResponse)
def review_page(request: Request, db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if redirect := _guard(flow, "review"):
        return redirect
    _draft_style_or_404(flow)
    return _page(
        request, flow, "review", "onboarding/review.html", {"rows": _review_rows(request, db, flow)}
    )


@router.post("/permbledhja", dependencies=[Depends(verify_csrf)])
def review_submit(request: Request, terms: str = Form(""), db: Session = Depends(get_db)):
    flow = _flow(request, db)
    if redirect := _guard(flow, "review"):
        return redirect
    style = _draft_style_or_404(flow)
    try:
        publish(db, shop=flow.shop, style=style, accepted_terms=bool(terms), now=clock.now())
    except OnboardingError as exc:
        db.rollback()
        errors = {"terms": ERRORS["terms"]} if exc.code == "terms" else {}
        return _page(
            request,
            flow,
            "review",
            "onboarding/review.html",
            {"rows": _review_rows(request, db, flow), "errors": errors},
            status_code=400,
        )
    db.commit()
    return _go("done")


@router.get("/gati", response_class=HTMLResponse)
def done_page(
    request: Request, db: Session = Depends(get_db), storage: Storage = Depends(get_storage)
):
    flow = _flow(request, db)
    if flow.style is None or not flow.style.published:
        return RedirectResponse(URLS[flow.reached()], status_code=303)
    style = flow.style
    first = sorted(style.images, key=lambda i: i.position)[0] if style.images else None
    return _page(
        request,
        flow,
        "done",
        "onboarding/done.html",
        {
            "style": style,
            "shop": flow.shop,
            "thumb": image_url(storage, first, "detail") if first else None,
            "photo_total": photo_count(db, style),
            "listing_url": f"/{flow.shop.slug}/{style.code}",
            "verified": flow.shop.verified_at is not None,
            "active_count": len([i for i in style.items if i.status == ItemStatus.ACTIVE.value]),
        },
    )
