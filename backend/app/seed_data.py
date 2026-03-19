from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(slots=True)
class SeedTrade:
    trade_time: str
    symbol: str
    name: str
    side: str
    order_price: float
    fill_price: float
    lots: int
    shares: int


SEED_CLOSE_PRICES: dict[str, dict[str, float]] = {
    "2026-03-16": {
        "000021": 33.10,
        "000547": 31.87,
    },
    "2026-03-17": {
        "000021": 32.26,
        "000547": 30.49,
    },
    "2026-03-18": {
        "000021": 33.63,
        "000547": 31.40,
    },
}

SEED_TRADES: list[SeedTrade] = [
    SeedTrade("2026-03-16 09:45:00", "000547", "航天发展", "BUY", 30.90, 30.90, 70, 7000),
    SeedTrade("2026-03-16 10:02:00", "000021", "深科技", "BUY", 31.13, 31.13, 60, 6000),
    SeedTrade("2026-03-16 10:30:00", "000021", "深科技", "BUY", 31.39, 31.39, 10, 1000),
    SeedTrade("2026-03-16 10:56:00", "000547", "航天发展", "BUY", 30.98, 30.98, 10, 1000),
    SeedTrade("2026-03-17 10:00:00", "000547", "航天发展", "SELL", 31.66, 31.66, 40, 4000),
    SeedTrade("2026-03-17 13:28:00", "000547", "航天发展", "BUY", 31.11, 31.11, 10, 1000),
    SeedTrade("2026-03-17 14:00:00", "000021", "深科技", "SELL", 32.47, 32.47, 30, 3000),
    SeedTrade("2026-03-18 09:35:00", "000547", "航天发展", "BUY", 30.35, 30.35, 10, 1000),
    SeedTrade("2026-03-18 10:30:00", "000021", "深科技", "BUY", 32.94, 32.94, 10, 1000),
    SeedTrade("2026-03-18 14:20:00", "000021", "深科技", "SELL", 33.70, 33.70, 40, 4000),
    SeedTrade("2026-03-18 14:30:00", "000547", "航天发展", "SELL", 31.67, 31.67, 20, 2000),
]


def parse_trade_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def event_times_for_trade(trade_time: datetime) -> dict[str, datetime]:
    created_at = trade_time - timedelta(minutes=10)
    pending_at = trade_time - timedelta(minutes=5)
    return {
        "created": created_at,
        "pending": pending_at,
        "triggered": trade_time,
        "filled": trade_time,
    }
