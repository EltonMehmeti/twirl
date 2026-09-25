from twirl.booking.dates import ShopRules
from twirl.models import Shop


def rules_for_shop(shop: Shop) -> ShopRules:
    return ShopRules(
        pickup_lead_days=shop.pickup_lead_days,
        return_after_days=shop.return_after_days,
        prep_days=shop.prep_days,
        cleaning_days=shop.cleaning_days,
        max_rental_days=shop.max_rental_days,
        closed_weekdays=frozenset(h.weekday for h in shop.hours if h.closed),
        closures=tuple((c.starts_on, c.ends_on) for c in shop.closures),
    )
