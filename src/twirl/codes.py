import secrets

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from twirl.models import Item

CODE_ALPHABET = "ACDEFHJKLMNPRTUVWXY3479"


def random_code(length: int) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def new_item_code(session: Session, shop_id: int) -> str:
    for _ in range(20):
        code = random_code(4)
        taken = session.scalar(select(exists().where(Item.shop_id == shop_id, Item.code == code)))
        if not taken:
            return code
    raise RuntimeError("could not allocate a free item code")


from twirl.models import Booking  # noqa: E402


def new_booking_ref(session: Session) -> str:
    for _ in range(20):
        ref = random_code(6)
        if not session.scalar(select(exists().where(Booking.ref == ref))):
            return ref
    raise RuntimeError("could not allocate a free booking reference")
