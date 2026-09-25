from twirl.models import BookingStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.HOLD: frozenset({S.PENDING_SHOP, S.CONFIRMED, S.EXPIRED}),
    S.PENDING_SHOP: frozenset({S.CONFIRMED, S.DECLINED, S.CANCELLED_BY_SHOP, S.CANCELLED_BY_RENTER}),
    S.CONFIRMED: frozenset(
        {S.AT_RISK, S.PICKED_UP, S.NO_SHOW, S.CANCELLED_BY_RENTER, S.CANCELLED_BY_SHOP}
    ),
    S.AT_RISK: frozenset({S.CONFIRMED, S.CANCELLED_BY_SHOP}),
    S.PICKED_UP: frozenset({S.COMPLETED, S.NOT_RETURNED}),
    S.NOT_RETURNED: frozenset({S.COMPLETED}),
}


def can_transition(src: S, dst: S) -> bool:
    return dst in TRANSITIONS.get(src, frozenset())
