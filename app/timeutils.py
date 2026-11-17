"""Dates and times. "Today" and "late" are decided in the daycares' time zone (TZ)."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.constants import CLOCK_SKEW_SECONDS, WEEKDAYS
from app.errors import ApiError

TZ = ZoneInfo(settings.tz)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return datetime.now(TZ).date()


def to_local(value: datetime) -> datetime:
    return value.astimezone(TZ)


def local_date(value: datetime) -> date:
    return to_local(value).date()


def local_hhmm(value: datetime) -> str:
    return to_local(value).strftime("%H:%M")


def hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def minutes_of(value: time) -> int:
    return value.hour * 60 + value.minute


def local_minutes(value: datetime) -> int:
    return minutes_of(to_local(value).time())


def weekday_name(day: date) -> str:
    return WEEKDAYS[day.weekday()]


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=TZ)


def day_end(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59, 999000), tzinfo=TZ)


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def monday_of_week(day: date) -> date:
    return day - timedelta(days=day.weekday())


def first_of_month(day: date) -> date:
    return day.replace(day=1)


def seconds(value: datetime) -> int:
    """The database keeps timestamps without milliseconds, so they are compared by seconds."""
    return int(value.timestamp() + 0.5)


def read_period(
    start: date | None,
    end: date | None,
    default_start: date | None = None,
    max_days: int = 100,
) -> tuple[date, date]:
    """Reads ?startDate=&endDate=. By default: from Monday of this week to today."""
    start = start or default_start or monday_of_week(today())
    end = end or today()
    if start > end:
        raise ApiError(400, "startDate cannot be after endDate")
    if (end - start).days + 1 > max_days:
        raise ApiError(400, f"The period cannot be longer than {max_days} days")
    return start, end


def read_timestamp(value: datetime | None) -> datetime:
    """A time sent by the client (for example a clock-in made offline that arrives later).

    No value means "now". A time without a UTC offset is read in the daycares' time zone.
    It cannot be in the future (a few minutes of clock difference are allowed).
    """
    if value is None:
        return now_utc()
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    value = value.astimezone(timezone.utc)
    if value > now_utc() + timedelta(seconds=CLOCK_SKEW_SECONDS):
        raise ApiError(400, "Invalid timestamp: it cannot be in the future")
    return value
