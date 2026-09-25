import secrets

from fastapi import HTTPException
from starlette.requests import Request

CSRF_SESSION_KEY = "csrf"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"


def get_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def verify_csrf(request: Request) -> None:
    expected = request.session.get(CSRF_SESSION_KEY)
    sent = request.headers.get(CSRF_HEADER)
    if not sent:
        form = await request.form()
        sent = form.get(CSRF_FIELD)
    if not expected or not isinstance(sent, str) or not secrets.compare_digest(expected, sent):
        raise HTTPException(status_code=403, detail="CSRF check failed")
