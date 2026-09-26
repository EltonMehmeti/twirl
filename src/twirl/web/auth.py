from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl import clock
from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import login_user, logout_user
from twirl.auth.passwords import verify_password
from twirl.db import get_db
from twirl.i18n import N_
from twirl.models import ShopUser, User
from twirl.otp import OtpError, TooMany, verify_code
from twirl.phones import InvalidPhone, display_phone, normalize_phone
from twirl.ratelimit import client_ip
from twirl.web.pages import safe_next
from twirl.web.phone_auth import SESSION_ECHO, resend_wait, send_code
from twirl.web.templating import render

router = APIRouter()


@router.get("/login")
def login_door(next_: str = Query("/shop", alias="next")):
    """Shops sign in with their phone: every public login link lands on the code login."""
    target = safe_next(next_, "/shop")
    suffix = "" if target == "/shop" else "?" + urlencode({"next": target})
    return RedirectResponse("/login/telefoni" + suffix, status_code=303)


# Email and password: only for shop accounts created from the command line. Not linked anywhere.
@router.get("/login/email", response_class=HTMLResponse)
def login_form(request: Request, next_: str = Query("/shop", alias="next")):
    return render(request, "auth/login.html", {"next": safe_next(next_, "/shop"), "error": None})


@router.post("/login/email", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_: str = Form("/shop", alias="next"),
    db: Session = Depends(get_db),
):
    target = safe_next(next_, "/shop")
    settings = request.app.state.settings
    if not request.app.state.login_limiter.allow(
        client_ip(request, trust_cf=settings.trust_cf_connecting_ip)
    ):
        return render(
            request,
            "auth/login.html",
            {"next": target, "error": N_("Too many attempts. Try again in a few minutes.")},
            status_code=429,
        )
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if (
        user is None
        or user.password_hash is None
        or user.blocked_at is not None
        or not verify_password(user.password_hash, password)
    ):
        return render(
            request,
            "auth/login.html",
            {"next": target, "error": N_("Wrong email or password.")},
            status_code=400,
        )
    login_user(request, user)
    return RedirectResponse(target, status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login/telefoni", status_code=303)


SESSION_LOGIN_PHONE = "login_phone"
SESSION_LOGIN_NEXT = "login_next"
PHONE_PAGE = {
    "action": "/login/telefoni",
    "eyebrow": N_("Provider login"),
    "lede": N_("We send a six-digit code to the number you listed with."),
    "back_url": "/",
}


def _limited(request: Request) -> bool:
    settings = request.app.state.settings
    ip = client_ip(request, trust_cf=settings.trust_cf_connecting_ip)
    return not request.app.state.login_limiter.allow(ip)


def _provider_by_phone(db: Session, phone: str) -> User | None:
    return db.scalar(
        select(User)
        .join(ShopUser, ShopUser.user_id == User.id)
        .where(User.phone == phone, User.blocked_at.is_(None))
    )


@router.get("/login/telefoni", response_class=HTMLResponse)
def phone_login_form(request: Request, next_: str | None = Query(None, alias="next")):
    if next_:
        request.session[SESSION_LOGIN_NEXT] = safe_next(next_, "/shop")
    return render(request, "auth/phone.html", {**PHONE_PAGE, "phone": "", "errors": {}})


@router.post("/login/telefoni", dependencies=[Depends(verify_csrf)])
def phone_login(request: Request, phone: str = Form(""), db: Session = Depends(get_db)):
    context = {**PHONE_PAGE, "phone": phone, "errors": {}}
    if _limited(request):
        return render(
            request,
            "auth/phone.html",
            {**context, "error": N_("Too many attempts. Try again in a few minutes.")},
            status_code=429,
        )
    try:
        e164 = normalize_phone(phone)
    except InvalidPhone:
        return render(
            request,
            "auth/phone.html",
            {**context, "errors": {"phone": N_("Write the number like 044 123 456.")}},
            status_code=400,
        )
    request.session[SESSION_LOGIN_PHONE] = e164
    if _provider_by_phone(db, e164) is not None:
        try:
            send_code(request, db, e164, "login")
        except TooMany:
            return render(
                request,
                "auth/phone.html",
                {**context, "error": N_("Too many codes for this number. Try again in an hour.")},
                status_code=429,
            )
        except OtpError:
            pass  # a code was sent seconds ago; the code screen shows the wait
        db.commit()
    return RedirectResponse("/login/kodi", status_code=303)


def _code_context(request: Request, db: Session, phone: str) -> dict:
    return {
        "action": "/login/kodi",
        "resend_action": "/login/telefoni/perseri",
        "change_url": "/login/telefoni",
        "eyebrow": N_("Provider login"),
        "phone_display": display_phone(phone),
        "resend_in": resend_wait(db, phone),
        "echo": request.session.get(SESSION_ECHO),
        "errors": {},
    }


@router.get("/login/kodi", response_class=HTMLResponse)
def phone_code_form(request: Request, db: Session = Depends(get_db)):
    phone = request.session.get(SESSION_LOGIN_PHONE)
    if not phone:
        return RedirectResponse("/login/telefoni", status_code=303)
    return render(request, "auth/code.html", _code_context(request, db, phone))


@router.post("/login/telefoni/perseri", dependencies=[Depends(verify_csrf)])
def phone_code_resend(request: Request, db: Session = Depends(get_db)):
    phone = request.session.get(SESSION_LOGIN_PHONE)
    if phone and _provider_by_phone(db, phone) is not None:
        try:
            send_code(request, db, phone, "login")
            db.commit()
        except OtpError:
            pass
    return RedirectResponse("/login/kodi", status_code=303)


@router.post("/login/kodi", dependencies=[Depends(verify_csrf)])
def phone_code_login(request: Request, code: str = Form(""), db: Session = Depends(get_db)):
    phone = request.session.get(SESSION_LOGIN_PHONE)
    if not phone:
        return RedirectResponse("/login/telefoni", status_code=303)
    context = _code_context(request, db, phone)
    if _limited(request):
        return render(
            request,
            "auth/code.html",
            {**context, "error": N_("Too many attempts. Try again in a few minutes.")},
            status_code=429,
        )
    settings = request.app.state.settings
    user = _provider_by_phone(db, phone)
    ok = verify_code(
        db, phone=phone, purpose="login", code=code, now=clock.now(), secret=settings.secret_key
    )
    db.commit()
    if not ok or user is None:
        return render(
            request,
            "auth/code.html",
            {**context, "errors": {"code": N_("That code is not right or has expired.")}},
            status_code=400,
        )
    target = request.session.get(SESSION_LOGIN_NEXT, "/shop")
    login_user(request, user)
    return RedirectResponse(safe_next(target, "/shop"), status_code=303)
