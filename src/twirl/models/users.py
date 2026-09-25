from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from twirl.models.base import Base, Timestamps, check_in


class UserKind(StrEnum):
    RENTER = "renter"
    SHOP = "shop"
    ADMIN = "admin"


class User(Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (check_in("kind", UserKind),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(5), default="sq", server_default=text("'sq'"))
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
