import phonenumbers


class InvalidPhone(ValueError):
    pass


def normalize_phone(raw: str, region: str = "XK") -> str:
    try:
        parsed = phonenumbers.parse(raw.strip(), region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhone(raw) from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhone(raw)
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
