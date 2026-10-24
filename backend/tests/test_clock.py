"""The user's calendar day (app/clock.py)."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.clock import local_date, parse_tz, user_tz


def test_parse_tz_accepts_iana_names_and_falls_back_to_utc():
    assert parse_tz("Asia/Kolkata") == ZoneInfo("Asia/Kolkata")
    for bad in (None, "", "Mars/Olympus", "../../etc/passwd", "/etc/localtime", "x" * 100):
        assert parse_tz(bad) is timezone.utc, bad


def test_local_date_buckets_timestamps_into_the_users_day():
    late_utc = datetime(2026, 10, 16, 20, 47, tzinfo=timezone.utc)  # 02:17 on the 17th in India
    assert local_date(late_utc) == date(2026, 10, 16)  # default: UTC
    token = user_tz.set(ZoneInfo("Asia/Kolkata"))
    try:
        assert local_date(late_utc) == date(2026, 10, 17)
        assert local_date(late_utc.replace(tzinfo=None)) == date(2026, 10, 17)  # naive = UTC
    finally:
        user_tz.reset(token)
