from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl.models import Channel, Notification, ShopRole, ShopUser, User
from twirl.notify.templates import ADMIN_RECIPIENT, TEMPLATES


def enqueue(
    session: Session, *, channel: Channel, recipient: str, template: str, payload: dict
) -> Notification:
    if template not in TEMPLATES:
        raise KeyError(template)
    notification = Notification(
        channel=channel.value, recipient=recipient, template=template, payload=payload
    )
    session.add(notification)
    return notification


def notify_admin(session: Session, template: str, payload: dict) -> Notification:
    return enqueue(
        session, channel=Channel.TELEGRAM, recipient=ADMIN_RECIPIENT, template=template,
        payload=payload,
    )


def notify_shop_owners(
    session: Session, shop_id: int, template: str, payload: dict
) -> list[Notification]:
    emails = session.scalars(
        select(User.email)
        .join(ShopUser, ShopUser.user_id == User.id)
        .where(
            ShopUser.shop_id == shop_id,
            ShopUser.role == ShopRole.OWNER.value,
            User.email.is_not(None),
        )
        .order_by(User.id)
    ).all()
    return [
        enqueue(session, channel=Channel.EMAIL, recipient=email, template=template, payload=payload)
        for email in emails
    ]
