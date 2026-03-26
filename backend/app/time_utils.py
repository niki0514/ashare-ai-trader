from __future__ import annotations

from datetime import datetime

from .market import CN_TZ, market_clock


MARKET_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ACCOUNT_BOOTSTRAP_TIME = datetime(1900, 1, 1, 0, 0, 0)


def market_now() -> datetime:
    return market_clock.now().replace(tzinfo=None)


def account_bootstrap_time() -> datetime:
    return ACCOUNT_BOOTSTRAP_TIME


def with_market_tz(value: datetime) -> datetime:
    if value.tzinfo:
        return value.astimezone(CN_TZ)
    return value.replace(tzinfo=CN_TZ)


def to_market_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return with_market_tz(value).replace(tzinfo=None)


def to_market_iso(value: datetime | None) -> str:
    if value is None:
        return market_clock.now().isoformat()
    return with_market_tz(value).isoformat()


def format_market_datetime(value: datetime) -> str:
    normalized = to_market_naive(value)
    assert normalized is not None
    return normalized.strftime(MARKET_DATETIME_FORMAT)


def combine_market_datetime(trade_date: str, time_text: str) -> datetime:
    return datetime.strptime(
        f"{trade_date} {time_text}", MARKET_DATETIME_FORMAT
    )


def trade_date_bounds(trade_date: str) -> tuple[datetime, datetime]:
    return (
        combine_market_datetime(trade_date, "00:00:00"),
        combine_market_datetime(trade_date, "23:59:59"),
    )
