from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from twirl import clock
from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import ShopContext, require_shop
from twirl.booking import staff
from twirl.booking.board import today_board, week_calendar
from twirl.booking.errors import InvalidDates, InvalidTransition, ItemConflict
from twirl.db import get_db
from twirl.i18n import N_
from twirl.models import Booking, BookingEvent, BookingKind, Item
from twirl.phones import InvalidPhone
from twirl.web.forms import form_data, validate_form
from twirl.web.messages import DATE_ERRORS, GENERIC_DATE_ERROR, STATUS_LABELS
from twirl.web.templating import render

router = APIRouter(prefix="/shop")

ACTIONS = {
    "pending_shop": [("accept", N_("Accept"), False), ("decline", N_("Decline"), True)],
    "confirmed": [("picked-up", N_("Picked up"), False), ("no-show", N_("No-show"), False),
                  ("cancel", N_("Cancel"), True)],
    "at_risk": [("cancel", N_("Cancel"), True)],
    "picked_up": [("returned-ok", N_("Returned OK"), False),
                  ("returned-issue", N_("Returned with an issue"), True)],
    "not_returned": [("returned-ok", N_("Returned OK"), False),
                     ("returned-issue", N_("Returned with an issue"), True)],
}
BLOCK_ACTIONS = [("cancel", N_("Remove block"), False)]
REASON_ACTIONS = {"decline", "cancel", "returned-issue"}


class WalkInForm(BaseModel):
    code: str = Field(min_length=4, max_length=4)
    kind: Literal["walk_in", "phone"] = "walk_in"
    pickup_date: date
    return_date: date
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=30)
    note: str = Field(default="", max_length=500)
    picked_up_now: bool = False
    override_reason: str = Field(default="", max_length=300)

    @field_validator("code", mode="before")
    @classmethod
    def _upper(cls, value):
        return str(value or "").strip().upper()

    @field_validator("picked_up_now", mode="before")
    @classmethod
    def _checkbox(cls, value):
        return bool(value) and value not in ("off", "false", "0")


def _get_booking(db: Session, ctx: ShopContext, booking_id: int) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.shop_id != ctx.shop.id:
        raise HTTPException(status_code=404)
    return booking


def _booking_page(request: Request, db: Session, ctx: ShopContext, booking: Booking, *,
                  error: str | None = None, status_code: int = 200):
    events = db.scalars(
        select(BookingEvent).where(BookingEvent.booking_id == booking.id).order_by(BookingEvent.id)
    ).all()
    is_block = booking.kind == BookingKind.BLOCK.value
    if is_block:
        actions = BLOCK_ACTIONS if booking.status == "confirmed" else []
    else:
        actions = ACTIONS.get(booking.status, [])
    candidates = (
        staff.swap_candidates(db, booking)
        if not is_block and booking.status in staff.SWAPPABLE else []
    )
    return render(
        request, "shop/booking.html",
        {"ctx": ctx, "b": booking, "events": events, "actions": actions, "candidates": candidates,
         "error": error, "status_labels": STATUS_LABELS},
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def today(request: Request, ctx: ShopContext = Depends(require_shop), db: Session = Depends(get_db)):
    day = clock.today()
    return render(request, "shop/today.html",
                  {"ctx": ctx, "board": today_board(db, ctx.shop.id, day), "today": day})


@router.get("/bookings/{booking_id}", response_class=HTMLResponse)
def booking_detail(request: Request, booking_id: int, ctx: ShopContext = Depends(require_shop),
                   db: Session = Depends(get_db)):
    return _booking_page(request, db, ctx, _get_booking(db, ctx, booking_id))


@router.post("/bookings/{booking_id}/{action}", dependencies=[Depends(verify_csrf)])
def booking_action(request: Request, booking_id: int, action: str,
                   form: FormData = Depends(form_data), ctx: ShopContext = Depends(require_shop),
                   db: Session = Depends(get_db)):
    booking = _get_booking(db, ctx, booking_id)
    reason = str(form.get("reason") or "")
    actor = ctx.actor
    try:
        match action:
            case "accept":
                staff.accept(db, booking, actor)
            case "decline":
                staff.decline(db, booking, actor, reason)
            case "picked-up":
                staff.mark_picked_up(db, booking, actor)
            case "returned-ok":
                staff.mark_returned(db, booking, actor, ok=True, note=reason)
            case "returned-issue":
                staff.mark_returned(db, booking, actor, ok=False, note=reason)
            case "no-show":
                staff.mark_no_show(db, booking, actor)
            case "cancel":
                if booking.kind == BookingKind.BLOCK.value:
                    staff.cancel_block(db, booking, actor)
                else:
                    staff.cancel_by_shop(db, booking, actor, reason)
            case "swap":
                item_id = str(form.get("item_id") or "")
                item = db.get(Item, int(item_id)) if item_id.isdigit() else None
                if item is None or item.shop_id != ctx.shop.id:
                    raise HTTPException(status_code=404)
                staff.swap_item(db, booking, item, actor=actor)
            case _:
                raise HTTPException(status_code=404)
    except (InvalidTransition, ItemConflict) as exc:
        db.rollback()
        message = (
            N_("That dress is taken on these dates. Pick another one.")
            if isinstance(exc, ItemConflict)
            else N_("That action is not possible for this booking any more.")
        )
        return _booking_page(request, db, ctx, booking, error=message, status_code=409)
    except ValueError:
        db.rollback()
        message = (
            N_("Please give a reason.") if action in REASON_ACTIONS
            else N_("Check the form and try again.")
        )
        return _booking_page(request, db, ctx, booking, error=message, status_code=400)
    db.commit()
    return RedirectResponse(f"/shop/bookings/{booking.id}", status_code=303)


def _walk_in_page(request: Request, db: Session, ctx: ShopContext, values: dict, *,
                  error: str | None = None, errors: dict | None = None, conflicts=None,
                  overridable: bool = False, status_code: int = 200):
    item = staff.find_item_by_code(db, ctx.shop.id, values["code"]) if len(values["code"]) == 4 else None
    return render(
        request, "shop/walk_in.html",
        {"ctx": ctx, "values": values, "item": item, "error": error, "errors": errors or {},
         "conflicts": conflicts or [], "overridable": overridable, "status_labels": STATUS_LABELS},
        status_code=status_code,
    )


@router.get("/walk-in", response_class=HTMLResponse)
def walk_in_form(request: Request, code: str = "", ctx: ShopContext = Depends(require_shop),
                 db: Session = Depends(get_db)):
    day = clock.today()
    values = {"code": code.strip().upper(), "kind": "walk_in", "pickup_date": day.isoformat(),
              "return_date": (day + timedelta(days=2)).isoformat(), "name": "", "phone": "",
              "note": "", "picked_up_now": True, "override_reason": ""}
    return _walk_in_page(request, db, ctx, values)


@router.post("/walk-in", dependencies=[Depends(verify_csrf)])
def create_walk_in(request: Request, form: FormData = Depends(form_data),
                   ctx: ShopContext = Depends(require_shop), db: Session = Depends(get_db)):
    keys = ("code", "kind", "pickup_date", "return_date", "name", "phone", "note", "override_reason")
    values = {key: str(form.get(key) or "") for key in keys}
    values["code"] = values["code"].strip().upper()
    values["picked_up_now"] = bool(form.get("picked_up_now"))
    parsed, errors = validate_form(WalkInForm, form)
    if parsed is None:
        return _walk_in_page(request, db, ctx, values, errors=errors,
                             error=N_("Check the highlighted fields."), status_code=400)
    item = staff.find_item_by_code(db, ctx.shop.id, parsed.code)
    if item is None:
        return _walk_in_page(request, db, ctx, values,
                             error=N_("No dress with this code in your shop."), status_code=400)
    try:
        booking = staff.create_staff_booking(
            db, shop=ctx.shop, item=item, pickup=parsed.pickup_date, return_=parsed.return_date,
            name=parsed.name, phone=parsed.phone, actor=ctx.actor, kind=BookingKind(parsed.kind),
            picked_up_now=parsed.picked_up_now, override_reason=parsed.override_reason or None,
            note=parsed.note,
        )
    except ItemConflict as exc:
        db.rollback()
        return _walk_in_page(request, db, ctx, values, conflicts=exc.conflicts,
                             overridable=exc.overridable,
                             error=N_("This dress is already booked on those dates."), status_code=409)
    except InvalidPhone:
        db.rollback()
        return _walk_in_page(request, db, ctx, values,
                             error=N_("That phone number does not look right."), status_code=400)
    except InvalidDates as exc:
        db.rollback()
        return _walk_in_page(request, db, ctx, values,
                             error=DATE_ERRORS.get(exc.code, GENERIC_DATE_ERROR), status_code=400)
    db.commit()
    return RedirectResponse(f"/shop/bookings/{booking.id}", status_code=303)


@router.get("/calendar", response_class=HTMLResponse)
def calendar(request: Request, start: date | None = None, ctx: ShopContext = Depends(require_shop),
             db: Session = Depends(get_db)):
    first = start or clock.today()
    days, rows = week_calendar(db, ctx.shop.id, first)
    return render(
        request, "shop/calendar.html",
        {"ctx": ctx, "days": days, "rows": rows,
         "prev": (first - timedelta(days=7)).isoformat(), "next": (first + timedelta(days=7)).isoformat()},
    )
