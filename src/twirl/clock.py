from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Belgrade")


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return datetime.now(TZ).date()
