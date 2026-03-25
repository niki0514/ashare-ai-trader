from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .market import market_clock
from .quote_client import to_quote_symbol
from .repositories import MarketDataRepository


def trade_date_of(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo:
        return value.astimezone(market_clock.now().tzinfo).date().isoformat()
    return value.date().isoformat()


@dataclass(slots=True)
class PriceSnapshot:
    open_price: float
    close_price: float
    previous_close: float
    market_value: float
    source: str
    is_final: bool
    updated_at: datetime | None


class MarketPriceResolver:
    def __init__(self, market_repo: MarketDataRepository):
        self.market_repo = market_repo

    def _from_intraday(self, symbol: str, trade_date: str, fallback: float):
        intraday = self.market_repo.latest_intraday_quote(to_quote_symbol(symbol), trade_date)
        previous_eod = self.market_repo.previous_eod_price(symbol, trade_date)
        if not intraday:
            return None
        previous_close = intraday.previous_close or (previous_eod.close_price if previous_eod else fallback)
        return PriceSnapshot(
            open_price=intraday.open_price or fallback,
            close_price=intraday.price or fallback,
            previous_close=previous_close or fallback,
            market_value=0.0,
            source="intraday",
            is_final=False,
            updated_at=intraday.quoted_at,
        )

    def _from_eod(self, symbol: str, trade_date: str, fallback: float):
        eod = self.market_repo.get_eod_price(symbol, trade_date)
        if not eod:
            return None
        previous_eod = self.market_repo.previous_eod_price(symbol, trade_date)
        previous_close = eod.previous_close or (previous_eod.close_price if previous_eod else fallback)
        return PriceSnapshot(
            open_price=eod.open_price or fallback,
            close_price=eod.close_price or fallback,
            previous_close=previous_close or fallback,
            market_value=0.0,
            source=eod.source or "eod",
            is_final=eod.is_final,
            updated_at=eod.published_at,
        )

    def _from_latest_eod(self, symbol: str, trade_date: str, fallback: float):
        eod = self.market_repo.latest_eod_price(symbol, trade_date)
        if not eod:
            return None
        previous_eod = self.market_repo.previous_eod_price(symbol, eod.trade_date)
        previous_close = eod.previous_close or (previous_eod.close_price if previous_eod else fallback)
        return PriceSnapshot(
            open_price=eod.open_price or fallback,
            close_price=eod.close_price or fallback,
            previous_close=previous_close or fallback,
            market_value=0.0,
            source=eod.source or "eod_history",
            is_final=eod.is_final,
            updated_at=eod.published_at,
        )

    def resolve_trade_date(
        self,
        symbol: str,
        trade_date: str,
        *,
        fallback: float,
        shares: int = 0,
        prefer_intraday: bool,
    ) -> PriceSnapshot:
        price = None
        if prefer_intraday:
            price = self._from_intraday(symbol, trade_date, fallback)
            if price is None:
                price = self._from_eod(symbol, trade_date, fallback)
        else:
            price = self._from_eod(symbol, trade_date, fallback)
            if price is None:
                price = self._from_intraday(symbol, trade_date, fallback)
        if price is None:
            price = self._from_latest_eod(symbol, trade_date, fallback)
        if price is None:
            price = PriceSnapshot(
                open_price=fallback,
                close_price=fallback,
                previous_close=fallback,
                market_value=0.0,
                source="fallback",
                is_final=False,
                updated_at=None,
            )
        price.market_value = shares * price.close_price
        return price

    def resolve_for_market_status(
        self,
        symbol: str,
        trade_date: str,
        *,
        market_status: str,
        fallback: float,
        shares: int = 0,
    ) -> PriceSnapshot:
        prefer_intraday = market_status in {"trading", "lunch_break"}
        if market_status == "closed":
            prefer_intraday = False
        return self.resolve_trade_date(
            symbol,
            trade_date,
            fallback=fallback,
            shares=shares,
            prefer_intraday=prefer_intraday,
        )
