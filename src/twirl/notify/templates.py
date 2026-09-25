from collections.abc import Callable

ADMIN_RECIPIENT = "admin"

Rendered = tuple[str, str]


def _new_request_shop(p: dict, base_url: str) -> Rendered:
    pending = p.get("status") == "pending_shop"
    subject = f"Kërkesë e re: {p['style_name']}, masa {p['size']} ({p['ref']})"
    lines = [
        "Keni një kërkesë të re për rezervim në Vesha."
        if pending
        else "Keni një rezervim të ri në Vesha.",
        "",
        f"Fustani: {p['style_name']} ({p['style_code']}), masa {p['size']}, kodi {p['item_code']}",
        f"Data e eventit: {p['event_date']}",
        f"Marrja: {p['pickup_date']} · Kthimi: {p['return_date']}",
        f"Klienti: {p['customer_name']}, {p['customer_phone']}",
        f"Kodi i rezervimit: {p['ref']}",
        "",
        f"Hapeni këtu: {base_url}{p['path']}",
    ]
    if pending:
        lines.append("Nëse nuk përgjigjeni brenda 24 orësh, kërkesa anulohet automatikisht.")
    return subject, "\n".join(lines)


def _new_request_admin(p: dict, base_url: str) -> Rendered:
    return "", (
        f"New {p['status']} booking {p['ref']} at {p['shop_name']}: {p['style_name']} "
        f"size {p['size']}, event {p['event_date']}. "
        f"{base_url}/admin/booking/list?search={p['ref']}"
    )


def _booking_at_risk_admin(p: dict, base_url: str) -> Rendered:
    return "", (
        f"AT RISK {p['ref']} at {p['shop_name']}: dress {p['item_code']} ({p['style_name']} "
        f"{p['size']}) was taken in store. Reason: {p['reason']}. "
        f"Renter: {p['customer_name']} {p['customer_phone']}. "
        f"{base_url}/admin/booking/list?search={p['ref']}"
    )


def _request_expired_admin(p: dict, base_url: str) -> Rendered:
    return "", (
        f"Request {p['ref']} at {p['shop_name']} was auto-cancelled after {p['hours']} h "
        f"with no reply. Renter: {p['customer_name']} {p['customer_phone']}."
    )


TEMPLATES: dict[str, Callable[[dict, str], Rendered]] = {
    "new_request_shop": _new_request_shop,
    "new_request_admin": _new_request_admin,
    "booking_at_risk_admin": _booking_at_risk_admin,
    "request_expired_admin": _request_expired_admin,
}


def render(template: str, payload: dict, *, base_url: str = "") -> Rendered:
    return TEMPLATES[template](payload, base_url)
