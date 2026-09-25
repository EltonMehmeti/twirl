from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import ShopContext, require_owner
from twirl.db import get_db
from twirl.i18n import N_
from twirl.models import ShopClosure, ShopHours
from twirl.phones import normalize_phone
from twirl.web.forms import form_data, validate_form
from twirl.web.templating import render

router = APIRouter(prefix="/shop/settings")

WEEKDAY_NAMES = [
    N_("Monday"), N_("Tuesday"), N_("Wednesday"), N_("Thursday"), N_("Friday"), N_("Saturday"),
    N_("Sunday"),
]
FIELDS = (
    "name", "city", "address", "phone", "whatsapp", "viber", "instagram", "terms_text",
    "pickup_lead_days", "return_after_days", "prep_days", "cleaning_days", "max_rental_days",
)
OPTIONAL_TEXT = ("phone", "whatsapp", "viber", "instagram")


class SettingsForm(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=60)
    address: str = Field(default="", max_length=255)
    phone: str = ""
    whatsapp: str = ""
    viber: str = ""
    instagram: str = Field(default="", max_length=60)
    terms_text: str = Field(default="", max_length=4000)
    pickup_lead_days: int = Field(ge=0, le=5)
    return_after_days: int = Field(ge=0, le=3)
    prep_days: int = Field(ge=0, le=2)
    cleaning_days: int = Field(ge=0, le=5)
    max_rental_days: int = Field(ge=1, le=14)
    closed_weekdays: list[int] = []

    @field_validator("phone", "whatsapp", "viber")
    @classmethod
    def _phone(cls, value: str) -> str:
        value = value.strip()
        return normalize_phone(value) if value else ""

    @field_validator("closed_weekdays")
    @classmethod
    def _weekdays(cls, value: list[int]) -> list[int]:
        if any(not 0 <= day <= 6 for day in value):
            raise ValueError("weekday out of range")
        return sorted(set(value))


class ClosureForm(BaseModel):
    starts_on: date
    ends_on: date
    reason: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _order(self) -> "ClosureForm":
        if self.ends_on < self.starts_on:
            raise ValueError("end before start")
        return self


def _values_from_shop(ctx: ShopContext) -> dict:
    values = {f: ("" if getattr(ctx.shop, f) is None else getattr(ctx.shop, f)) for f in FIELDS}
    values["closed_weekdays"] = [h.weekday for h in ctx.shop.hours if h.closed]
    return values


def _values_from_form(form: FormData) -> dict:
    values = {f: form.get(f, "") for f in FIELDS}
    values["closed_weekdays"] = [int(v) for v in form.getlist("closed_weekdays") if str(v).isdigit()]
    return values


def _page(request: Request, ctx: ShopContext, *, values: dict, errors: dict | None = None,
          status_code: int = 200, saved: bool = False):
    return render(
        request, "shop/settings.html",
        {
            "ctx": ctx, "values": values, "errors": errors or {}, "saved": saved,
            "weekdays": list(enumerate(WEEKDAY_NAMES)), "closures": ctx.shop.closures,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, saved: bool = False, ctx: ShopContext = Depends(require_owner)):
    return _page(request, ctx, values=_values_from_shop(ctx), saved=saved)


@router.post("", dependencies=[Depends(verify_csrf)])
def save_settings(
    request: Request,
    form: FormData = Depends(form_data),
    ctx: ShopContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    parsed, errors = validate_form(SettingsForm, form, list_fields=("closed_weekdays",))
    if parsed is None:
        return _page(request, ctx, values=_values_from_form(form), errors=errors, status_code=400)
    shop = ctx.shop
    for field in FIELDS:
        value = getattr(parsed, field)
        setattr(shop, field, (value or None) if field in OPTIONAL_TEXT else value)
    existing = {h.weekday: h for h in shop.hours}
    for weekday in range(7):
        hours = existing.get(weekday)
        if hours is None:
            hours = ShopHours(weekday=weekday)
            shop.hours.append(hours)
        hours.closed = weekday in parsed.closed_weekdays
    db.commit()
    return RedirectResponse("/shop/settings?saved=true", status_code=303)


@router.post("/closures", dependencies=[Depends(verify_csrf)])
def add_closure(
    request: Request,
    form: FormData = Depends(form_data),
    ctx: ShopContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    parsed, errors = validate_form(ClosureForm, form)
    if parsed is None:
        return _page(request, ctx, values=_values_from_shop(ctx), errors=errors, status_code=400)
    ctx.shop.closures.append(
        ShopClosure(starts_on=parsed.starts_on, ends_on=parsed.ends_on, reason=parsed.reason.strip())
    )
    db.commit()
    return RedirectResponse("/shop/settings", status_code=303)


@router.post("/closures/{closure_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_closure(
    closure_id: int, ctx: ShopContext = Depends(require_owner), db: Session = Depends(get_db)
):
    closure = db.get(ShopClosure, closure_id)
    if closure is None or closure.shop_id != ctx.shop.id:
        raise HTTPException(status_code=404)
    ctx.shop.closures.remove(closure)
    db.commit()
    return RedirectResponse("/shop/settings", status_code=303)
