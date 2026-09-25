from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, SmallInteger, String, Text, Time, func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twirl.models.base import Base, Timestamps, check_in
from twirl.models.users import User


class ShopStatus(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    PUBLISHED = "published"
    SUSPENDED = "suspended"


class BookingMode(StrEnum):
    REQUEST = "request"
    INSTANT = "instant"


class ShopRole(StrEnum):
    OWNER = "owner"
    STAFF = "staff"


def _small(default: int):
    return mapped_column(SmallInteger, default=default, server_default=text(str(default)))


class Shop(Timestamps, Base):
    __tablename__ = "shops"
    __table_args__ = (
        check_in("status", ShopStatus),
        check_in("booking_mode", BookingMode),
        CheckConstraint("pickup_lead_days BETWEEN 0 AND 5", name="pickup_lead_days"),
        CheckConstraint("return_after_days BETWEEN 0 AND 3", name="return_after_days"),
        CheckConstraint("prep_days BETWEEN 0 AND 2", name="prep_days"),
        CheckConstraint("cleaning_days BETWEEN 0 AND 5", name="cleaning_days"),
        CheckConstraint("max_rental_days BETWEEN 1 AND 14", name="max_rental_days"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(60))
    address: Mapped[str] = mapped_column(String(255), default="", server_default=text("''"))
    phone: Mapped[str | None] = mapped_column(String(20))
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    viber: Mapped[str | None] = mapped_column(String(20))
    instagram: Mapped[str | None] = mapped_column(String(60))
    terms_text: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    pickup_lead_days: Mapped[int] = _small(2)
    return_after_days: Mapped[int] = _small(1)
    prep_days: Mapped[int] = _small(0)
    cleaning_days: Mapped[int] = _small(1)
    max_rental_days: Mapped[int] = _small(7)
    booking_mode: Mapped[str] = mapped_column(
        String(16), default=BookingMode.REQUEST.value, server_default=text("'request'")
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ShopStatus.DRAFT.value, server_default=text("'draft'")
    )

    hours: Mapped[list["ShopHours"]] = relationship(
        back_populates="shop", order_by="ShopHours.weekday", cascade="all, delete-orphan"
    )
    closures: Mapped[list["ShopClosure"]] = relationship(
        back_populates="shop", order_by="ShopClosure.starts_on", cascade="all, delete-orphan"
    )


class ShopHours(Base):
    __tablename__ = "shop_hours"
    __table_args__ = (CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),)

    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True)
    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    opens: Mapped[time | None] = mapped_column(Time)
    closes: Mapped[time | None] = mapped_column(Time)
    closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    shop: Mapped[Shop] = relationship(back_populates="hours")


class ShopClosure(Timestamps, Base):
    __tablename__ = "shop_closures"
    __table_args__ = (CheckConstraint("ends_on >= starts_on", name="range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))

    shop: Mapped[Shop] = relationship(back_populates="closures")


class ShopUser(Timestamps, Base):
    __tablename__ = "shop_users"
    __table_args__ = (check_in("role", ShopRole),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    role: Mapped[str] = mapped_column(String(16))

    shop: Mapped[Shop] = relationship()
    user: Mapped[User] = relationship()


class ShopCustomer(Base):
    __tablename__ = "shop_customers"

    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    first_booking_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
