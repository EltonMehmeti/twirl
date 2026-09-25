from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twirl.models.base import Base, Timestamps, check_in
from twirl.models.catalog import Item, Style
from twirl.models.shops import Shop
from twirl.models.users import User


class BookingKind(StrEnum):
    ONLINE = "online"
    WALK_IN = "walk_in"
    PHONE = "phone"
    BLOCK = "block"


class BookingStatus(StrEnum):
    HOLD = "hold"
    PENDING_SHOP = "pending_shop"
    CONFIRMED = "confirmed"
    AT_RISK = "at_risk"
    PICKED_UP = "picked_up"
    COMPLETED = "completed"
    CANCELLED_BY_RENTER = "cancelled_by_renter"
    CANCELLED_BY_SHOP = "cancelled_by_shop"
    EXPIRED = "expired"
    NO_SHOW = "no_show"
    NOT_RETURNED = "not_returned"
    DECLINED = "declined"


class ActorKind(StrEnum):
    RENTER = "renter"
    SHOP = "shop"
    ADMIN = "admin"
    SYSTEM = "system"


class ConditionKind(StrEnum):
    INTAKE = "intake"
    RETURNED_OK = "returned_ok"
    RETURNED_ISSUE = "returned_issue"
    STATUS_CHANGE = "status_change"


ACTIVE_STATUSES: tuple[str, ...] = ("hold", "pending_shop", "confirmed", "picked_up")
_ACTIVE_SQL = "status IN ('hold', 'pending_shop', 'confirmed', 'picked_up')"


class Booking(Timestamps, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "style_id", "shop_id"],
            ["items.id", "items.style_id", "items.shop_id"],
            name="fk_bookings_item_style_shop",
        ),
        CheckConstraint("return_date >= pickup_date", name="dates_order"),
        check_in("kind", BookingKind),
        check_in("status", BookingStatus),
        ExcludeConstraint(
            ("item_id", "="),
            ("blocked_range", "&&"),
            name="ex_bookings_item_overlap",
            using="gist",
            where=text(_ACTIVE_SQL),
        ),
        Index("ix_bookings_shop_pickup", "shop_id", "pickup_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(8), unique=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    item_id: Mapped[int] = mapped_column()
    style_id: Mapped[int] = mapped_column()
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    event_date: Mapped[date | None] = mapped_column(Date)
    pickup_date: Mapped[date] = mapped_column(Date)
    return_date: Mapped[date] = mapped_column(Date)
    prep_days: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    cleaning_days: Mapped[int] = mapped_column(SmallInteger, default=1, server_default=text("1"))
    blocked_range: Mapped[Range[date]] = mapped_column(
        DATERANGE,
        Computed(
            "daterange(pickup_date - prep_days, return_date + cleaning_days, '[]')",
            persisted=True,
        ),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_channel: Mapped[str | None] = mapped_column(String(20))
    fee_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    price_cents: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    customer_note: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    staff_note: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    reason: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    shop: Mapped[Shop] = relationship(viewonly=True)
    item: Mapped[Item] = relationship(
        viewonly=True, primaryjoin="Booking.item_id == Item.id", foreign_keys="Booking.item_id"
    )
    style: Mapped[Style] = relationship(
        viewonly=True, primaryjoin="Booking.style_id == Style.id", foreign_keys="Booking.style_id"
    )
    customer: Mapped[User | None] = relationship(viewonly=True, foreign_keys=[customer_id])


class BookingEvent(Base):
    __tablename__ = "booking_events"
    __table_args__ = (check_in("actor_kind", ActorKind),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ItemConditionEvent(Base):
    __tablename__ = "item_condition_events"
    __table_args__ = (check_in("kind", ConditionKind),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    kind: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
