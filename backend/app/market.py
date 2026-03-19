from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import settings


CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(slots=True)
class MarketSession:
    market_status: str
    trade_date: str
    time: str


class MarketClock:
    def now(self) -> datetime:
        if settings.market_now_override:
            raw = settings.market_now_override.strip()
            if raw.endswith("Z"):
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(CN_TZ)
            parsed = datetime.fromisoformat(raw)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=CN_TZ)
        return datetime.now(CN_TZ)

    def get_session(self, now: datetime | None = None) -> MarketSession:
        current = now.astimezone(CN_TZ) if now and now.tzinfo else (now.replace(tzinfo=CN_TZ) if now else self.now())
        trade_date = current.strftime("%Y-%m-%d")
        time_text = current.strftime("%H:%M:%S")
        weekday = current.weekday()

        if weekday >= 5:
            return MarketSession(market_status="weekend", trade_date=trade_date, time=time_text)
        if time_text < "09:30:00":
            return MarketSession(market_status="pre_open", trade_date=trade_date, time=time_text)
        if time_text <= "11:30:00":
            return MarketSession(market_status="trading", trade_date=trade_date, time=time_text)
        if time_text < "13:00:00":
            return MarketSession(market_status="lunch_break", trade_date=trade_date, time=time_text)
        if time_text <= "15:00:00":
            return MarketSession(market_status="trading", trade_date=trade_date, time=time_text)
        return MarketSession(market_status="closed", trade_date=trade_date, time=time_text)

    def is_market_polling_window(self, now: datetime | None = None) -> bool:
        return self.get_session(now).market_status == "trading"

    def is_import_window_open(self, now: datetime | None = None) -> bool:
        return self.get_session(now).market_status in {"pre_open", "closed"}


market_clock = MarketClock()
