"""The user's calendar day.

Timestamps are stored and compared in UTC. "Today" (which plan items are due, which
days count as practised, how many days until an interview) means the *user's* local
date. The web client sends its IANA zone in an `X-Timezone` header; TimezoneMiddleware
puts it in `user_tz` for the request. No header, or an unknown zone, means UTC.

Use `user_today()` for calendar-day logic and `local_date()` to bucket a stored
timestamp into the user's day. Never use `date.today()`: that is the server's zone.
"""
from __future__ import annotations

import contextvars
from datetime import date, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

user_tz: contextvars.ContextVar[tzinfo] = contextvars.ContextVar("user_tz", default=timezone.utc)


def parse_tz(name: str | None) -> tzinfo:
    """IANA zone name -> tzinfo. Anything missing, malformed or unknown falls back to UTC."""
    if not name or len(name) > 64 or ".." in name or name.startswith("/"):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def user_tz_name() -> str | None:
    """The IANA name the client sent this request, or None (no header, or unknown -> UTC)."""
    return getattr(user_tz.get(), "key", None)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def user_today() -> date:
    return datetime.now(user_tz.get()).date()


def local_date(dt: datetime) -> date:
    """The user's calendar day for a stored timestamp (naive timestamps are UTC)."""
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return aware.astimezone(user_tz.get()).date()
