import re

RESERVED_SLUGS = frozenset(
    {"admin", "api", "healthz", "lang", "listo", "login", "logout", "media", "r", "shop", "static"}
)
_SLUG_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.fullmatch(slug)) and slug not in RESERVED_SLUGS
