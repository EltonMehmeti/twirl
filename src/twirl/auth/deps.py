from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl.booking.actor import Actor
from twirl.db import get_db
from twirl.models import ActorKind, Shop, ShopRole, ShopUser, User

SESSION_USER_KEY = "uid"


class LoginRequired(Exception):
    def __init__(self, next_path: str) -> None:
        super().__init__(next_path)
        self.next_path = next_path


@dataclass(frozen=True)
class ShopContext:
    user: User
    shop: Shop
    role: str

    @property
    def is_owner(self) -> bool:
        return self.role == ShopRole.OWNER.value

    @property
    def actor(self) -> Actor:
        return Actor(ActorKind.SHOP, self.user.id)


def login_user(request: Request, user: User) -> None:
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id


def logout_user(request: Request) -> None:
    request.session.clear()


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or user.blocked_at is not None:
        return None
    return user


def require_shop(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
) -> ShopContext:
    if user is None:
        raise LoginRequired(request.url.path)
    link = db.scalar(select(ShopUser).where(ShopUser.user_id == user.id))
    if link is None:
        raise HTTPException(status_code=403)
    return ShopContext(user=user, shop=db.get(Shop, link.shop_id), role=link.role)


def require_owner(ctx: ShopContext = Depends(require_shop)) -> ShopContext:
    if not ctx.is_owner:
        raise HTTPException(status_code=403)
    return ctx
