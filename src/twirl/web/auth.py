from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl.auth.csrf import verify_csrf
from twirl.auth.deps import login_user, logout_user
from twirl.auth.passwords import verify_password
from twirl.db import get_db
from twirl.i18n import N_
from twirl.models import User
from twirl.ratelimit import client_ip
from twirl.web.pages import safe_next
from twirl.web.templating import render

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next_: str = Query("/shop", alias="next")):
    return render(request, "auth/login.html", {"next": safe_next(next_, "/shop"), "error": None})


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_: str = Form("/shop", alias="next"),
    db: Session = Depends(get_db),
):
    target = safe_next(next_, "/shop")
    settings = request.app.state.settings
    if not request.app.state.login_limiter.allow(client_ip(request, trust_cf=settings.trust_cf_connecting_ip)):
        return render(
            request, "auth/login.html",
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
            request, "auth/login.html",
            {"next": target, "error": N_("Wrong email or password.")}, status_code=400,
        )
    login_user(request, user)
    return RedirectResponse(target, status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)
