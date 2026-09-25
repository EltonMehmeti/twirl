from datetime import date

from twirl.models import Booking


def fmt_date(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def booking_payload(booking: Booking) -> dict:
    customer = booking.customer
    return {
        "ref": booking.ref,
        "status": booking.status,
        "shop_name": booking.shop.name,
        "style_name": booking.style.name,
        "style_code": booking.style.code,
        "size": booking.item.size,
        "item_code": booking.item.code,
        "event_date": fmt_date(booking.event_date),
        "pickup_date": fmt_date(booking.pickup_date),
        "return_date": fmt_date(booking.return_date),
        "customer_name": customer.name if customer else "",
        "customer_phone": customer.phone if customer and customer.phone else "",
        "path": f"/shop/bookings/{booking.id}",
    }
