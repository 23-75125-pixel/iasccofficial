import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Asia/Manila"


def configured_timezone_name():
    return os.getenv("APP_TIMEZONE") or os.getenv("TZ") or DEFAULT_TIMEZONE


def configured_timezone():
    timezone_name = configured_timezone_name()
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name != DEFAULT_TIMEZONE:
            try:
                return ZoneInfo(DEFAULT_TIMEZONE)
            except ZoneInfoNotFoundError:
                pass
        return timezone(timedelta(hours=8), DEFAULT_TIMEZONE)


def now():
    return datetime.now(configured_timezone())
