from twirl.i18n import N_

STATUS_LABELS = {
    "hold": N_("On hold"),
    "pending_shop": N_("Waiting for your answer"),
    "confirmed": N_("Confirmed"),
    "at_risk": N_("At risk"),
    "picked_up": N_("Picked up"),
    "completed": N_("Returned"),
    "cancelled_by_renter": N_("Cancelled by customer"),
    "cancelled_by_shop": N_("Cancelled by shop"),
    "expired": N_("Expired"),
    "no_show": N_("No-show"),
    "not_returned": N_("Not returned"),
    "declined": N_("Declined"),
}

DATE_ERRORS = {
    "pickup_in_past": N_("That date is too soon for this shop. Pick a later date."),
    "return_before_pickup": N_("The return date must be on or after the pickup date."),
    "too_long": N_("That rental is longer than this shop allows."),
    "event_outside_rental": N_("The event date must fall between pickup and return."),
    "pickup_closed": N_("The shop is closed on the pickup day."),
    "return_closed": N_("The shop is closed on the return day."),
    "no_open_day": N_("The shop is closed around that date."),
}
GENERIC_DATE_ERROR = N_("Those dates do not work for this shop.")
