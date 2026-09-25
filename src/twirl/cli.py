import argparse
from getpass import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from twirl.auth.passwords import hash_password
from twirl.config import get_settings
from twirl.db import Database
from twirl.models import Shop, ShopRole, ShopStatus, ShopUser, User, UserKind
from twirl.slugs import is_valid_slug

MIN_PASSWORD_LENGTH = 8


def _login_user(session: Session, *, kind: UserKind, email: str, name: str, password: str) -> User:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError("password must be at least 8 characters")
    user = User(kind=kind.value, name=name.strip(), email=email.strip().lower(),
                password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def cmd_create_admin(session: Session, *, email: str, name: str, password: str) -> User:
    return _login_user(session, kind=UserKind.ADMIN, email=email, name=name, password=password)


def cmd_create_shop(
    session: Session, *, slug: str, name: str, city: str, owner_email: str, owner_name: str,
    owner_password: str, staff_email: str | None = None, staff_password: str | None = None,
) -> Shop:
    if not is_valid_slug(slug):
        raise ValueError(f"invalid or reserved slug: {slug}")
    shop = Shop(slug=slug, name=name.strip(), city=city.strip(), status=ShopStatus.DRAFT.value)
    session.add(shop)
    session.flush()
    owner = _login_user(session, kind=UserKind.SHOP, email=owner_email, name=owner_name,
                        password=owner_password)
    session.add(ShopUser(shop_id=shop.id, user_id=owner.id, role=ShopRole.OWNER.value))
    if staff_email:
        staff = _login_user(session, kind=UserKind.SHOP, email=staff_email, name=f"{name} staff",
                            password=staff_password or "")
        session.add(ShopUser(shop_id=shop.id, user_id=staff.id, role=ShopRole.STAFF.value))
    session.flush()
    return shop


def cmd_publish_shop(session: Session, *, slug: str) -> Shop:
    shop = session.scalars(select(Shop).where(Shop.slug == slug)).one()
    shop.status = ShopStatus.PUBLISHED.value
    session.flush()
    return shop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="twirl")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    shop = sub.add_parser("create-shop")
    for flag in ("--slug", "--name", "--city", "--owner-email", "--owner-name"):
        shop.add_argument(flag, required=True)
    shop.add_argument("--staff-email")
    publish = sub.add_parser("publish-shop")
    publish.add_argument("--slug", required=True)
    args = parser.parse_args(argv)

    db = Database(get_settings().database_url)
    with db.sessionmaker() as session:
        if args.command == "create-admin":
            cmd_create_admin(session, email=args.email, name=args.name, password=getpass("Admin password: "))
        elif args.command == "create-shop":
            cmd_create_shop(
                session, slug=args.slug, name=args.name, city=args.city,
                owner_email=args.owner_email, owner_name=args.owner_name,
                owner_password=getpass("Owner password: "),
                staff_email=args.staff_email,
                staff_password=getpass("Staff password: ") if args.staff_email else None,
            )
        else:
            cmd_publish_shop(session, slug=args.slug)
        session.commit()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
