from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from twirl.models.base import Base, Timestamps, check_in


class Channel(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"


class NotificationStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class Notification(Timestamps, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        check_in("channel", Channel),
        check_in("status", NotificationStatus),
        Index("ix_notifications_queued", "id", postgresql_where=text("status = 'queued'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(16))
    recipient: Mapped[str] = mapped_column(String(254))
    template: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(
        String(16), default=NotificationStatus.QUEUED.value, server_default=text("'queued'")
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    last_error: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    provider_id: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
