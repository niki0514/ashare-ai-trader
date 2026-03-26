from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import settings
from .trading_calendar import trading_calendar


CN_TZ = ZoneInfo("Asia/Shanghai")


def next_trading_date(trade_date: str) -> str:
    return trading_calendar.next_trading_date(trade_date)


def previous_trading_date(trade_date: str) -> str:
    return trading_calendar.previous_trading_date(trade_date)


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
        if not trading_calendar.is_trading_day(trade_date):
            return MarketSession(market_status="holiday", trade_date=trade_date, time=time_text)
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
        return self.get_session(now).market_status != "trading"

    def minimum_import_trade_date(self, now: datetime | None = None) -> str:
        session = self.get_session(now)
        if session.market_status in {"pre_open", "trading", "lunch_break"}:
            return session.trade_date
        return next_trading_date(session.trade_date)

    def validate_import_trade_date(
        self,
        target_trade_date: str,
        now: datetime | None = None,
    ) -> str | None:
        try:
            date.fromisoformat(target_trade_date)
        except ValueError:
            return "挂单时间格式需为 YYYY-MM-DD"

        if not trading_calendar.is_trading_day(target_trade_date):
            return f"挂单时间 {target_trade_date} 不是交易日，请选择交易日"

        minimum_trade_date = self.minimum_import_trade_date(now)
        if target_trade_date >= minimum_trade_date:
            return None

        session = self.get_session(now)
        if session.market_status == "closed":
            return f"{session.trade_date} 已收盘，挂单时间必须晚于 {session.trade_date}"
        if session.market_status in {"weekend", "holiday"}:
            return f"当前为休市时段，挂单时间不能早于下一个交易日 {minimum_trade_date}"
        return f"挂单时间不能早于当前交易日 {minimum_trade_date}"

    def suggested_import_trade_date(self, now: datetime | None = None) -> str:
        return self.minimum_import_trade_date(now)


market_clock = MarketClock()
