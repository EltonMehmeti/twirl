from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from twirl.models import ShopCustomer, User, UserKind


def get_or_create_customer(session: Session, *, phone: str, name: str) -> User:
    session.execute(
        pg_insert(User)
        .values(kind=UserKind.RENTER.value, name=name.strip()[:120], phone=phone)
        .on_conflict_do_nothing(index_elements=["phone"])
    )
    return session.scalars(select(User).where(User.phone == phone)).one()


def link_customer(session: Session, *, shop_id: int, user_id: int) -> None:
    session.execute(
        pg_insert(ShopCustomer)
        .values(shop_id=shop_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["shop_id", "user_id"])
    )
