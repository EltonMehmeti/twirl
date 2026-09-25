from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from twirl.auth.passwords import verify_password
from twirl.config import Settings
from twirl.db import Database
from twirl.models import (
    Booking, BookingEvent, Item, Notification, Shop, Style, User, UserKind,
)

ADMIN_SESSION_KEY = "admin_uid"


class AdminAuth(AuthenticationBackend):
    def __init__(self, secret_key: str, db: Database) -> None:
        super().__init__(secret_key=secret_key)
        self._db = db

    def _check(self, email: str, password: str) -> int | None:
        with self._db.sessionmaker() as session:
            user = session.scalar(
                select(User).where(User.email == email, User.kind == UserKind.ADMIN.value)
            )
            if (
                user is not None
                and user.password_hash
                and user.blocked_at is None
                and verify_password(user.password_hash, password)
            ):
                return user.id
        return None

    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = str(form.get("username", "")).strip().lower()
        password = str(form.get("password", ""))
        user_id = await run_in_threadpool(self._check, email, password)
        if user_id is None:
            return False
        request.session.update({ADMIN_SESSION_KEY: user_id})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return ADMIN_SESSION_KEY in request.session


class ShopAdmin(ModelView, model=Shop):
    column_list = [Shop.id, Shop.slug, Shop.name, Shop.city, Shop.status, Shop.booking_mode]
    column_searchable_list = [Shop.slug, Shop.name]
    form_columns = [
        Shop.name, Shop.city, Shop.address, Shop.phone, Shop.whatsapp, Shop.viber, Shop.instagram,
        Shop.status, Shop.booking_mode, Shop.pickup_lead_days, Shop.return_after_days,
        Shop.prep_days, Shop.cleaning_days, Shop.max_rental_days,
    ]
    can_delete = False


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.kind, User.name, User.email, User.phone, User.blocked_at]
    column_searchable_list = [User.email, User.phone, User.name]
    form_columns = [User.name, User.email, User.phone, User.locale, User.blocked_at]
    can_create = False
    can_delete = False


class StyleAdmin(ModelView, model=Style):
    column_list = [Style.id, Style.shop_id, Style.code, Style.name, Style.price_cents, Style.published]
    column_searchable_list = [Style.name, Style.code]
    form_columns = [Style.name, Style.description, Style.price_cents, Style.published]
    can_create = False
    can_delete = False


class ItemAdmin(ModelView, model=Item):
    column_list = [Item.id, Item.shop_id, Item.style_id, Item.code, Item.size, Item.status]
    column_searchable_list = [Item.code]
    form_columns = [Item.size, Item.status, Item.notes]
    can_create = False
    can_delete = False


class BookingAdmin(ModelView, model=Booking):
    column_list = [
        Booking.id, Booking.ref, Booking.shop_id, Booking.item_id, Booking.kind, Booking.status,
        Booking.pickup_date, Booking.return_date, Booking.created_at,
    ]
    column_searchable_list = [Booking.ref]
    column_sortable_list = [Booking.created_at, Booking.pickup_date]
    column_default_sort = [(Booking.created_at, True)]
    can_create = False
    can_edit = False
    can_delete = False


class BookingEventAdmin(ModelView, model=BookingEvent):
    column_list = [
        BookingEvent.id, BookingEvent.booking_id, BookingEvent.from_status, BookingEvent.to_status,
        BookingEvent.actor_kind, BookingEvent.reason, BookingEvent.created_at,
    ]
    column_default_sort = [(BookingEvent.id, True)]
    can_create = False
    can_edit = False
    can_delete = False


class NotificationAdmin(ModelView, model=Notification):
    column_list = [
        Notification.id, Notification.channel, Notification.recipient, Notification.template,
        Notification.status, Notification.attempts, Notification.last_error, Notification.created_at,
    ]
    column_default_sort = [(Notification.id, True)]
    can_create = False
    can_edit = False
    can_delete = False


def mount_admin(app: FastAPI, db: Database, settings: Settings) -> Admin:
    admin = Admin(
        app, engine=db.engine, session_maker=db.sessionmaker, base_url="/admin", title="Twirl admin",
        authentication_backend=AdminAuth(settings.secret_key, db),
    )
    for view in (ShopAdmin, UserAdmin, StyleAdmin, ItemAdmin, BookingAdmin, BookingEventAdmin,
                 NotificationAdmin):
        admin.add_view(view)
    return admin
