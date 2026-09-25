from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twirl.models.base import Base, Timestamps, check_in
from twirl.models.shops import Shop


class Occasion(StrEnum):
    WEDDING = "wedding"
    ENGAGEMENT = "engagement"
    MATURA = "matura"
    HENNA_NIGHT = "henna_night"
    EVENING = "evening"


class ColourFamily(StrEnum):
    BLACK = "black"
    WHITE = "white"
    RED = "red"
    PINK = "pink"
    BLUE = "blue"
    GREEN = "green"
    GOLD = "gold"
    SILVER = "silver"
    BEIGE = "beige"
    PURPLE = "purple"
    MULTI = "multi"


class DressLength(StrEnum):
    MINI = "mini"
    MIDI = "midi"
    MAXI = "maxi"


class ItemStatus(StrEnum):
    ACTIVE = "active"
    CLEANING = "cleaning"
    REPAIR = "repair"
    RETIRED = "retired"
    LOST = "lost"


class Style(Timestamps, Base):
    __tablename__ = "styles"
    __table_args__ = (
        UniqueConstraint("shop_id", "code"),
        CheckConstraint("price_cents >= 0", name="price"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    price_cents: Mapped[int] = mapped_column(Integer)
    occasion_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default=text("'{}'")
    )
    colour_family: Mapped[str | None] = mapped_column(String(16))
    length: Mapped[str | None] = mapped_column(String(8))
    stretch: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    adjustable_back: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    shop: Mapped[Shop] = relationship()
    images: Mapped[list["StyleImage"]] = relationship(
        back_populates="style", order_by="StyleImage.position", cascade="all, delete-orphan"
    )
    items: Mapped[list["Item"]] = relationship(back_populates="style", order_by="Item.id")


class StyleImage(Timestamps, Base):
    __tablename__ = "style_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    style_id: Mapped[int] = mapped_column(ForeignKey("styles.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    storage_key: Mapped[str] = mapped_column(String(200))
    width: Mapped[int] = mapped_column(SmallInteger)
    height: Mapped[int] = mapped_column(SmallInteger)

    style: Mapped[Style] = relationship(back_populates="images")


class Item(Timestamps, Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("shop_id", "code"),
        UniqueConstraint("id", "style_id", "shop_id", name="uq_items_id_style_shop"),
        check_in("status", ItemStatus),
        Index("ix_items_style_size", "style_id", "size"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    style_id: Mapped[int] = mapped_column(ForeignKey("styles.id"))
    code: Mapped[str] = mapped_column(String(4))
    size: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(
        String(16), default=ItemStatus.ACTIVE.value, server_default=text("'active'")
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))

    style: Mapped[Style] = relationship(back_populates="items")
