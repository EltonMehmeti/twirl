from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from twirl.models.base import Base, check_in


class CodePurpose(StrEnum):
    SIGNUP = "signup"
    LOGIN = "login"


class PhoneCode(Base):
    """One SMS verification code. Only a keyed hash of the code is stored."""

    __tablename__ = "phone_codes"
    __table_args__ = (check_in("purpose", CodePurpose),)

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    purpose: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
