from __future__ import annotations

from datetime import date, timedelta

from .config import settings


OFFICIAL_SSE_CLOSED_DATE_RANGES: dict[int, tuple[tuple[str, str], ...]] = {
    2024: (
        ("2024-01-01", "2024-01-01"),
        ("2024-02-09", "2024-02-17"),
        ("2024-04-04", "2024-04-06"),
        ("2024-05-01", "2024-05-05"),
        ("2024-06-10", "2024-06-10"),
        ("2024-09-15", "2024-09-17"),
        ("2024-10-01", "2024-10-07"),
    ),
    2025: (
        ("2025-01-01", "2025-01-01"),
        ("2025-01-28", "2025-02-04"),
        ("2025-04-04", "2025-04-06"),
        ("2025-05-01", "2025-05-05"),
        ("2025-05-31", "2025-06-02"),
        ("2025-10-01", "2025-10-08"),
    ),
    2026: (
        ("2026-01-01", "2026-01-03"),
        ("2026-02-15", "2026-02-23"),
        ("2026-04-04", "2026-04-06"),
        ("2026-05-01", "2026-05-05"),
        ("2026-06-19", "2026-06-21"),
        ("2026-09-25", "2026-09-27"),
        ("2026-10-01", "2026-10-07"),
    ),
}


def _expand_closed_ranges(ranges: tuple[tuple[str, str], ...]) -> set[str]:
    dates: set[str] = set()
    for start_text, end_text in ranges:
        current = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
        while current <= end:
            dates.add(current.isoformat())
            current += timedelta(days=1)
    return dates


BUILTIN_CLOSED_DATES = {
    trade_date
    for ranges in OFFICIAL_SSE_CLOSED_DATE_RANGES.values()
    for trade_date in _expand_closed_ranges(ranges)
}


def configured_closed_dates() -> set[str]:
    raw = settings.market_holiday_dates.strip()
    if raw == "":
        return set()
    return {value.strip() for value in raw.split(",") if value.strip()}


class TradingCalendar:
    def is_trading_day(self, trade_date: str) -> bool:
        current = date.fromisoformat(trade_date)
        if current.weekday() >= 5:
            return False
        return trade_date not in BUILTIN_CLOSED_DATES | configured_closed_dates()

    def next_trading_date(self, trade_date: str) -> str:
        current = date.fromisoformat(trade_date)
        while True:
            current += timedelta(days=1)
            candidate = current.isoformat()
            if self.is_trading_day(candidate):
                return candidate

    def previous_trading_date(self, trade_date: str) -> str:
        current = date.fromisoformat(trade_date)
        while True:
            current -= timedelta(days=1)
            candidate = current.isoformat()
            if self.is_trading_day(candidate):
                return candidate


trading_calendar = TradingCalendar()
