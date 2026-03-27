from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .db import session_scope
from .market import market_clock, next_trading_date, previous_trading_date
from .market_prices import MarketPriceResolver, trade_date_of
from .models import DailyPnlDetail, ExecutionTrade, InstructionOrder, OrderSide, OrderStatus, PositionLot, PositionStatus, User
from .quote_client import TencentQuoteClient, to_quote_symbol
from .repositories import (
    MarketDataRepository,
    OrderRepository,
    PnlRepository,
    PortfolioRepository,
    UserRepository,
)
from .time_utils import (
    combine_market_datetime,
    format_market_datetime,
    market_now,
    to_market_iso,
    trade_date_bounds,
)


def format_dt(value: datetime) -> str:
    return format_market_datetime(value)


def to_iso(value: datetime | None) -> str:
    return to_market_iso(value)


def _next_trading_open(after: datetime) -> datetime:
    target_trade_date = next_trading_date(after.date().isoformat())
    return combine_market_datetime(target_trade_date, "09:30:00").replace(
        tzinfo=after.tzinfo
    )


def engine_sleep_seconds(now: datetime | None = None) -> float:
    current = now.astimezone(market_clock.now().tzinfo) if now and now.tzinfo else (now.replace(tzinfo=market_clock.now().tzinfo) if now else market_clock.now())
    session_info = market_clock.get_session(current)

    if session_info.market_status == "trading":
        return settings.quote_poll_seconds
    if session_info.market_status == "pre_open":
        target = current.replace(hour=9, minute=30, second=0, microsecond=0)
    elif session_info.market_status == "lunch_break":
        target = current.replace(hour=13, minute=0, second=0, microsecond=0)
    elif session_info.market_status in {"closed", "weekend", "holiday"}:
        target = _next_trading_open(current)
    else:
        target = current

    return max(0.5, (target - current).total_seconds())


class QuoteService:
    def __init__(self, session: Session):
        self.session = session
        self.market_repo = MarketDataRepository(session)
        self.quote_client = TencentQuoteClient()

    def _store_quotes(self, rows) -> list[dict]:
        now = market_now()
        result: list[dict] = []
        for row in rows:
            quoted_at = row.updated_at or now
            saved = self.market_repo.append_intraday_quote(
                {
                    "symbol": row.symbol,
                    "name": row.name,
                    "trade_date": trade_date_of(quoted_at) or trade_date_of(now),
                    "price": row.price,
                    "open": row.open_price,
                    "previousClose": row.previous_close,
                    "high": row.high_price,
                    "low": row.low_price,
                    "quoted_at": quoted_at,
                    "source": "tencent",
                }
            )
            result.append(
                {
                    "symbol": saved.symbol,
                    "name": saved.symbol_name or saved.symbol,
                    "price": saved.price,
                    "open": saved.open_price,
                    "previousClose": saved.previous_close,
                    "high": saved.high_price,
                    "low": saved.low_price,
                    "updatedAt": to_market_iso(saved.quoted_at),
                }
            )
        return result

    async def fetch_and_store_quotes(self, symbols: list[str]) -> list[dict]:
        normalized = sorted(set(to_quote_symbol(s) for s in symbols if s))
        return self._store_quotes(await self.quote_client.fetch_quotes(normalized))

    def fetch_and_store_quotes_sync(self, symbols: list[str]) -> list[dict]:
        normalized = sorted(set(to_quote_symbol(s) for s in symbols if s))
        return self._store_quotes(self.quote_client.fetch_quotes_sync(normalized))

    def get_quotes(self, symbols: list[str] | None = None) -> list[dict]:
        rows = self.market_repo.list_latest_intraday_quotes([to_quote_symbol(s) for s in symbols] if symbols else None)
        return [
            {
                "symbol": row.symbol,
                "name": row.symbol_name or row.symbol,
                "price": row.price,
                "open": row.open_price,
                "previousClose": row.previous_close,
                "high": row.high_price,
                "low": row.low_price,
                "updatedAt": to_market_iso(row.quoted_at),
            }
            for row in rows
        ]

    def latest_updated_at(self) -> str:
        dt = self.market_repo.latest_intraday_updated_at()
        return to_iso(dt)


class PnlService:
    def __init__(self, session: Session):
        self.session = session
        self.portfolio_repo = PortfolioRepository(session)
        self.pnl_repo = PnlRepository(session)
        self.market_repo = MarketDataRepository(session)
        self.price_resolver = MarketPriceResolver(self.market_repo)

    def _build_position_snapshot(self, user_id: str, trade_date: str) -> dict[str, dict[str, Any]]:
        _, end = trade_date_bounds(trade_date)
        stmt = (
            select(ExecutionTrade, InstructionOrder)
            .join(InstructionOrder, InstructionOrder.id == ExecutionTrade.order_id)
            .where(ExecutionTrade.user_id == user_id, ExecutionTrade.fill_time <= end)
            .order_by(ExecutionTrade.fill_time.asc(), ExecutionTrade.id.asc())
        )
        fifo_lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for trade, order in self.session.execute(stmt).all():
            if trade.side == OrderSide.BUY:
                fifo_lots[trade.symbol].append(
                    {
                        "shares": trade.shares,
                        "costPrice": trade.fill_price,
                        "symbolName": order.symbol_name or trade.symbol,
                    }
                )
                continue
            remaining = trade.shares
            for lot in fifo_lots[trade.symbol]:
                if remaining <= 0:
                    break
                consumed = min(lot["shares"], remaining)
                lot["shares"] -= consumed
                remaining -= consumed
            fifo_lots[trade.symbol] = [lot for lot in fifo_lots[trade.symbol] if lot["shares"] > 0]

        grouped: dict[str, dict[str, Any]] = {}
        for symbol, lots in fifo_lots.items():
            shares = sum(lot["shares"] for lot in lots)
            cost_amount = sum(lot["shares"] * lot["costPrice"] for lot in lots)
            if shares <= 0:
                continue
            grouped[symbol] = {
                "symbol": symbol,
                "symbolName": lots[-1]["symbolName"] if lots else symbol,
                "shares": shares,
                "costAmount": cost_amount,
                "fallbackPrice": cost_amount / shares if shares else 0.0,
            }
        return grouped

    def trade_date_symbols(self, user_id: str, trade_date: str) -> list[str]:
        symbols = set(self._build_position_snapshot(user_id, trade_date).keys())
        previous_day = self.pnl_repo.previous_daily_pnl(user_id, trade_date)
        if previous_day:
            symbols.update(
                detail.symbol
                for detail in previous_day.details
                if detail.closing_shares > 0
            )
        start, end = trade_date_bounds(trade_date)
        stmt = select(ExecutionTrade.symbol).where(
            ExecutionTrade.user_id == user_id,
            ExecutionTrade.fill_time >= start,
            ExecutionTrade.fill_time <= end,
        )
        symbols.update(self.session.scalars(stmt).all())
        return sorted(symbols)

    def materialize_trade_date_eod_prices_from_next_day(
        self,
        user_id: str,
        trade_date: str,
        *,
        next_trade_date: str,
        source: str,
    ) -> bool:
        ready_to_finalize = True
        published_at = combine_market_datetime(trade_date, "15:00:00")
        for symbol in self.trade_date_symbols(user_id, trade_date):
            current_eod = self.market_repo.get_eod_price(symbol, trade_date)
            if current_eod and current_eod.is_final:
                continue

            next_eod = self.market_repo.get_eod_price(symbol, next_trade_date)
            next_quote = self.market_repo.latest_intraday_quote(to_quote_symbol(symbol), next_trade_date)

            next_previous_close = 0.0
            symbol_name = symbol
            if next_eod and next_eod.previous_close > 0:
                next_previous_close = next_eod.previous_close
                symbol_name = next_eod.symbol_name or symbol_name
            elif next_quote and next_quote.previous_close > 0:
                next_previous_close = next_quote.previous_close
                symbol_name = next_quote.symbol_name or symbol_name
            else:
                ready_to_finalize = False
                continue

            previous_eod = self.market_repo.previous_eod_price(symbol, trade_date)
            self.market_repo.upsert_eod_price(
                symbol=symbol,
                symbol_name=symbol_name,
                trade_date=trade_date,
                close_price=next_previous_close,
                open_price=next_previous_close,
                previous_close=previous_eod.close_price if previous_eod else next_previous_close,
                high_price=next_previous_close,
                low_price=next_previous_close,
                is_final=True,
                source=source,
                published_at=published_at,
            )
        return ready_to_finalize

    def materialize_trade_date_eod_prices(
        self,
        user_id: str,
        trade_date: str,
        *,
        is_final: bool,
        source: str,
    ) -> bool:
        ready_to_finalize = True
        for symbol in self.trade_date_symbols(user_id, trade_date):
            current_eod = self.market_repo.get_eod_price(symbol, trade_date)
            if current_eod and current_eod.is_final and is_final:
                continue

            quote = self.market_repo.latest_intraday_quote(to_quote_symbol(symbol), trade_date)
            if not quote:
                ready_to_finalize = False
                continue

            previous_eod = self.market_repo.previous_eod_price(symbol, trade_date)
            self.market_repo.upsert_eod_price(
                symbol=symbol,
                symbol_name=quote.symbol_name or (current_eod.symbol_name if current_eod else symbol),
                trade_date=trade_date,
                close_price=quote.price,
                open_price=quote.open_price or (current_eod.open_price if current_eod else quote.price),
                previous_close=quote.previous_close or (previous_eod.close_price if previous_eod else quote.price),
                high_price=quote.high_price or quote.price,
                low_price=quote.low_price or quote.price,
                is_final=is_final,
                source=source,
                published_at=quote.quoted_at,
            )
        return ready_to_finalize

    def _price_snapshot(self, symbol: str, shares: int, fallback: float, trade_date: str, use_realtime: bool) -> tuple[float, float, float]:
        price = self.price_resolver.resolve_trade_date(
            symbol,
            trade_date,
            fallback=fallback,
            shares=shares,
            prefer_intraday=use_realtime,
        )
        return price.open_price or fallback, price.close_price or fallback, price.market_value

    def recompute_daily_pnl(
        self,
        user_id: str,
        trade_date: str,
        *,
        use_realtime: bool,
        is_final: bool = False,
        persist: bool = True,
    ) -> dict:
        _, as_of_end = trade_date_bounds(trade_date)
        available_cash = self.portfolio_repo.cash_balance(user_id, before=as_of_end)

        grouped = self._build_position_snapshot(user_id, trade_date)

        previous_day = self.pnl_repo.previous_daily_pnl(user_id, trade_date)
        first_day = self.pnl_repo.first_daily_pnl(user_id)
        previous_details = {
            d.symbol: {"shares": d.closing_shares, "price": d.close_price}
            for d in (previous_day.details if previous_day else [])
            if d.closing_shares > 0
        }

        start, end = trade_date_bounds(trade_date)
        trades_stmt = (
            select(ExecutionTrade)
            .where(ExecutionTrade.user_id == user_id, ExecutionTrade.fill_time >= start, ExecutionTrade.fill_time <= end)
            .options(selectinload(ExecutionTrade.order))
        )
        today_trades = list(self.session.scalars(trades_stmt).all())

        trade_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "symbolName": "",
                "buyShares": 0,
                "buyAmount": 0.0,
                "sellShares": 0,
                "sellAmount": 0.0,
                "costBasisAmount": 0.0,
            }
        )
        for trade in today_trades:
            cur = trade_stats[trade.symbol]
            if not cur["symbolName"]:
                order = trade.order
                cur["symbolName"] = (order.symbol_name if order and order.symbol_name else trade.symbol)
            if trade.side == OrderSide.BUY:
                cur["buyShares"] += trade.shares
                cur["buyAmount"] += trade.fill_price * trade.shares
            else:
                cur["sellShares"] += trade.shares
                cur["sellAmount"] += trade.fill_price * trade.shares
                cur["costBasisAmount"] += trade.cost_basis_amount

        if trade_stats:
            lots = self.portfolio_repo.all_lots(user_id)
            for symbol, current in trade_stats.items():
                if current["sellShares"] == 0 or current["costBasisAmount"] > 0:
                    continue
                symbol_lots = [l for l in lots if l.symbol == symbol]
                total_original = sum(l.original_shares for l in symbol_lots)
                avg_cost = (sum(l.cost_price * l.original_shares for l in symbol_lots) / total_original) if total_original > 0 else 0.0
                current["costBasisAmount"] = avg_cost * current["sellShares"]

        detail_symbols = set(grouped.keys()) | set(previous_details.keys()) | set(trade_stats.keys())
        detail_rows: list[dict] = []
        for symbol in sorted(detail_symbols):
            current_holding = grouped.get(symbol)
            previous = previous_details.get(symbol)
            stat = trade_stats.get(symbol)

            closing_shares = current_holding["shares"] if current_holding else 0
            previous_shares = previous["shares"] if previous else 0
            buy_shares = stat["buyShares"] if stat else 0
            buy_amount = stat["buyAmount"] if stat else 0.0
            sell_shares = stat["sellShares"] if stat else 0
            sell_amount = stat["sellAmount"] if stat else 0.0
            realized_cost_basis = stat["costBasisAmount"] if stat else 0.0

            if (
                previous_shares == 0
                and closing_shares == 0
                and buy_shares == 0
                and sell_shares == 0
            ):
                continue

            cost_amount = current_holding["costAmount"] if current_holding else 0.0
            fallback_price = (
                current_holding["fallbackPrice"]
                if current_holding
                else (previous["price"] if previous else 0.0)
            )
            open_price, close_price, market_value = self._price_snapshot(
                symbol,
                closing_shares,
                fallback_price,
                trade_date,
                use_realtime,
            )
            previous_price = previous["price"] if previous else fallback_price

            avg_sell_price = (sell_amount / sell_shares) if sell_shares else 0.0
            buy_price = (cost_amount / closing_shares) if closing_shares > 0 else ((realized_cost_basis / sell_shares) if sell_shares > 0 else 0.0)

            # 统一单票日收益公式：
            # detailDailyPnl = closePrice * closingShares + sellAmount - prevClose * openingShares - buyAmount
            daily_pnl = close_price * closing_shares + sell_amount - previous_price * previous_shares - buy_amount

            denominator = (
                previous_shares * previous_price
                if previous_shares > 0
                else (buy_amount if buy_shares > 0 else (realized_cost_basis if realized_cost_basis > 0 else 1.0))
            )
            detail_rows.append(
                {
                    "symbol": symbol,
                    "symbolName": (current_holding["symbolName"] if current_holding else (stat["symbolName"] if stat else symbol)),
                    "openingShares": previous_shares,
                    "closingShares": closing_shares,
                    "buyShares": buy_shares,
                    "sellShares": sell_shares,
                    "buyPrice": buy_price,
                    "sellPrice": avg_sell_price,
                    "openPrice": open_price,
                    "closePrice": close_price,
                    "dailyPnl": daily_pnl,
                    "dailyReturn": 0.0 if denominator == 0 else daily_pnl / denominator,
                    "marketValue": market_value,
                }
            )

        position_market_value = sum(r["marketValue"] for r in detail_rows)
        total_assets = available_cash + position_market_value
        user = self.session.get(User, user_id)
        initial_capital = user.initial_cash if user else ((first_day.total_assets - first_day.cumulative_pnl) if first_day else total_assets)
        previous_total_assets = previous_day.total_assets if previous_day else initial_capital
        daily_pnl_total = total_assets - previous_total_assets
        daily_return = 0.0 if previous_total_assets == 0 else daily_pnl_total / previous_total_assets
        cumulative_pnl = total_assets - initial_capital
        buy_amount = sum(t.fill_price * t.shares for t in today_trades if t.side == OrderSide.BUY)
        sell_amount = sum(t.fill_price * t.shares for t in today_trades if t.side == OrderSide.SELL)

        payload = {
            "totalAssets": total_assets,
            "availableCash": available_cash,
            "positionMarketValue": position_market_value,
            "dailyPnl": daily_pnl_total,
            "dailyReturn": daily_return,
            "cumulativePnl": cumulative_pnl,
            "buyAmount": buy_amount,
            "sellAmount": sell_amount,
            "tradeCount": len(today_trades),
            "details": detail_rows,
        }
        if persist:
            self.pnl_repo.upsert_daily_pnl(
                user_id=user_id,
                trade_date=trade_date,
                payload=payload,
                is_final=is_final,
            )
        return payload


class SettlementService:
    def __init__(self, session: Session):
        self.session = session
        self.order_repo = OrderRepository(session)
        self.pnl_repo = PnlRepository(session)
        self.pnl_service = PnlService(session)
        self.quote_service = QuoteService(session)

    @staticmethod
    def _payload_from_daily(row) -> dict:
        return {
            "totalAssets": row.total_assets,
            "availableCash": row.available_cash,
            "positionMarketValue": row.position_market_value,
            "dailyPnl": row.daily_pnl,
            "dailyReturn": row.daily_return,
            "cumulativePnl": row.cumulative_pnl,
            "buyAmount": row.buy_amount,
            "sellAmount": row.sell_amount,
            "tradeCount": row.trade_count,
            "details": [
                {
                    "symbol": detail.symbol,
                    "symbolName": detail.symbol_name or detail.symbol,
                    "openingShares": detail.opening_shares,
                    "closingShares": detail.closing_shares,
                    "buyShares": detail.buy_shares,
                    "sellShares": detail.sell_shares,
                    "buyPrice": detail.buy_price,
                    "sellPrice": detail.sell_price,
                    "openPrice": detail.open_price,
                    "closePrice": detail.close_price,
                    "dailyPnl": detail.daily_pnl,
                    "dailyReturn": detail.daily_return,
                    "marketValue": detail.closing_shares * detail.close_price,
                }
                for detail in row.details
            ],
        }

    def _refresh_trade_date_quotes(self, user_id: str, trade_date: str) -> None:
        symbols = self.pnl_service.trade_date_symbols(user_id, trade_date)
        missing_symbols = [
            symbol
            for symbol in symbols
            if self.quote_service.market_repo.latest_intraday_quote(
                to_quote_symbol(symbol),
                trade_date,
            )
            is None
        ]
        if not missing_symbols:
            return
        try:
            self.quote_service.fetch_and_store_quotes_sync(missing_symbols)
        except Exception:
            # Query-side settlement should fall back to already cached quotes
            # instead of failing the whole request when the upstream quote source blips.
            return

    def _should_persist_trade_date(self, user_id: str, trade_date: str) -> bool:
        if self.pnl_service.trade_date_symbols(user_id, trade_date):
            return True
        return self.pnl_repo.previous_daily_pnl(user_id, trade_date) is not None

    def expire_day_orders(self, user_id: str, trade_date: str) -> None:
        for order in self.order_repo.list_day_orders_to_expire(user_id, trade_date):
            self.order_repo.update_order_status(
                order,
                status="expired",
                status_reason="当日未触价已失效",
            )
            self.order_repo.add_event(order.id, "expired", "当日未触价已失效")

    def ensure_final_snapshot(
        self,
        user_id: str,
        trade_date: str,
        *,
        refresh_quotes: bool,
        source: str,
        force_recompute: bool = False,
    ) -> dict | None:
        existing = self.pnl_repo.get_daily_pnl(user_id, trade_date)
        if existing and existing.is_final and not force_recompute:
            return self._payload_from_daily(existing)
        if not force_recompute and not self._should_persist_trade_date(
            user_id, trade_date
        ):
            return None

        if refresh_quotes:
            self._refresh_trade_date_quotes(user_id, trade_date)

        can_finalize = self.pnl_service.materialize_trade_date_eod_prices(
            user_id,
            trade_date,
            is_final=True,
            source=source,
        )
        payload = self.pnl_service.recompute_daily_pnl(
            user_id,
            trade_date,
            use_realtime=False,
            is_final=can_finalize,
            persist=True,
        )
        if can_finalize:
            self.expire_day_orders(user_id, trade_date)
        return payload

    def backfill_pending_history(self, user_id: str, current_trade_date: str) -> None:
        for trade_date in self.pnl_repo.list_non_final_trade_dates(
            user_id,
            before_trade_date=current_trade_date,
        ):
            self.ensure_final_snapshot(
                user_id,
                trade_date,
                refresh_quotes=False,
                source="close_backfill",
            )

    def backfill_missing_previous_trade_date(
        self, user_id: str, current_trade_date: str
    ) -> bool:
        target_trade_date = previous_trading_date(current_trade_date)
        if self.pnl_repo.get_daily_pnl(user_id, target_trade_date):
            return False
        if not self.pnl_repo.previous_daily_pnl(user_id, target_trade_date):
            return False

        can_finalize = self.pnl_service.materialize_trade_date_eod_prices_from_next_day(
            user_id,
            target_trade_date,
            next_trade_date=current_trade_date,
            source="next_day_previous_close",
        )
        if not can_finalize:
            return False

        self.pnl_service.recompute_daily_pnl(
            user_id,
            target_trade_date,
            use_realtime=False,
            is_final=True,
            persist=True,
        )
        self.expire_day_orders(user_id, target_trade_date)
        return True

    def ensure_session_snapshot(self, user_id: str, market_session) -> dict | None:
        self.backfill_pending_history(user_id, market_session.trade_date)
        previous_trade_date_backfilled = False
        if market_session.market_status in {"trading", "lunch_break", "closed"}:
            previous_trade_date_backfilled = self.backfill_missing_previous_trade_date(
                user_id, market_session.trade_date
            )

        if market_session.market_status == "trading":
            if not settings.engine_enabled:
                self._refresh_trade_date_quotes(user_id, market_session.trade_date)
            return self.pnl_service.recompute_daily_pnl(
                user_id,
                market_session.trade_date,
                use_realtime=True,
                is_final=False,
                persist=False,
            )

        if market_session.market_status == "lunch_break":
            if not self._should_persist_trade_date(user_id, market_session.trade_date):
                return None
            if not settings.engine_enabled:
                self._refresh_trade_date_quotes(user_id, market_session.trade_date)
            return self.pnl_service.recompute_daily_pnl(
                user_id,
                market_session.trade_date,
                use_realtime=True,
                is_final=False,
                persist=True,
            )

        if market_session.market_status == "closed":
            return self.ensure_final_snapshot(
                user_id,
                market_session.trade_date,
                refresh_quotes=True,
                source="close_settlement",
                force_recompute=previous_trade_date_backfilled,
            )

        return None


class QueryService:
    def __init__(self, session: Session):
        self.session = session
        self.order_repo = OrderRepository(session)
        self.portfolio_repo = PortfolioRepository(session)
        self.pnl_repo = PnlRepository(session)
        self.market_repo = MarketDataRepository(session)
        self.price_resolver = MarketPriceResolver(self.market_repo)
        self.pnl_service = PnlService(session)
        self.quote_service = QuoteService(session)
        self.settlement = SettlementService(session)

    def get_dashboard(self, user_id: str) -> dict:
        market_session = market_clock.get_session()
        trade_date = market_session.trade_date
        current_snapshot = self.settlement.ensure_session_snapshot(
            user_id, market_session
        )

        open_lots = self.portfolio_repo.open_lots(user_id)
        position_market_value = 0.0
        for lot in open_lots:
            price = self.price_resolver.resolve_for_market_status(
                lot.symbol,
                trade_date,
                market_status=market_session.market_status,
                fallback=lot.cost_price,
                shares=lot.remaining_shares,
            )
            position_market_value += price.market_value

        available_cash = self.portfolio_repo.cash_balance(user_id)
        total_assets = available_cash + position_market_value
        reference_trade_date = (
            previous_trading_date(trade_date)
            if market_session.market_status in {"pre_open", "weekend", "holiday"}
            else trade_date
        )
        latest_final = self.pnl_repo.latest_daily_pnl(
            user_id,
            before_trade_date=reference_trade_date,
            final_only=True,
        )
        user = self.session.get(User, user_id)
        fallback_cumulative = total_assets - (user.initial_cash if user else total_assets)

        if current_snapshot is not None:
            total_assets = current_snapshot["totalAssets"]
            available_cash = current_snapshot["availableCash"]
            position_market_value = current_snapshot["positionMarketValue"]
            daily_pnl = current_snapshot["dailyPnl"]
            cumulative_pnl = current_snapshot["cumulativePnl"]
        else:
            daily_pnl = 0.0
            cumulative_pnl = (
                latest_final.cumulative_pnl if latest_final else fallback_cumulative
            )

        return {
            "tradeDate": trade_date,
            "suggestedImportTradeDate": market_clock.suggested_import_trade_date(),
            "marketStatus": market_session.market_status,
            "updatedAt": self.quote_service.latest_updated_at(),
            "metrics": {
                "totalAssets": total_assets,
                "availableCash": available_cash,
                "positionMarketValue": position_market_value,
                "dailyPnl": daily_pnl,
                "cumulativePnl": cumulative_pnl,
                "exposureRatio": 0.0 if total_assets == 0 else position_market_value / total_assets,
            },
        }

    def _sync_visible_day_order_statuses(self, user_id: str) -> None:
        market_session = market_clock.get_session()
        trade_dates: list[str] = []
        if market_session.market_status == "closed":
            trade_dates = [market_session.trade_date]
        elif market_session.market_status in {"weekend", "holiday"}:
            trade_dates = [previous_trading_date(market_session.trade_date)]

        for trade_date in trade_dates:
            self.settlement.expire_day_orders(user_id, trade_date)

    def get_positions(self, user_id: str) -> list[dict]:
        self._sync_visible_day_order_statuses(user_id)
        market_session = market_clock.get_session()
        trade_date = market_session.trade_date
        lots = self.portfolio_repo.open_lots(user_id)
        pending_sell = self.portfolio_repo.get_pending_sell_orders_by_symbol(
            user_id, trade_date
        )
        trade_totals: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "name": "",
                "buyShares": 0,
                "sellShares": 0,
                "buyAmount": 0.0,
                "sellAmount": 0.0,
            }
        )
        trade_stmt = (
            select(ExecutionTrade, InstructionOrder)
            .join(InstructionOrder, InstructionOrder.id == ExecutionTrade.order_id)
            .where(ExecutionTrade.user_id == user_id)
            .order_by(ExecutionTrade.fill_time.asc(), ExecutionTrade.id.asc())
        )
        for trade, order in self.session.execute(trade_stmt).all():
            current = trade_totals[trade.symbol]
            if not current["name"]:
                current["name"] = order.symbol_name or trade.symbol
            amount = trade.fill_price * trade.shares
            if trade.side == OrderSide.BUY:
                current["buyShares"] += trade.shares
                current["buyAmount"] += amount
            else:
                current["sellShares"] += trade.shares
                current["sellAmount"] += amount

        grouped: dict[str, dict[str, Any]] = {}
        for lot in lots:
            projected_sellable = lot.remaining_shares if lot.opened_date < trade_date else lot.sellable_shares
            current = grouped.setdefault(
                lot.symbol,
                {
                    "symbol": lot.symbol,
                    "name": lot.symbol_name or lot.symbol,
                    "shares": 0,
                    "sellableShares": 0,
                    "frozenSellShares": 0,
                    "costPrice": 0.0,
                    "costAmount": 0.0,
                    "lastPrice": lot.cost_price,
                    "todayPnl": 0.0,
                    "todayReturn": 0.0,
                },
            )
            total_shares = current["shares"] + lot.remaining_shares
            current["costAmount"] += lot.cost_price * lot.remaining_shares
            current["shares"] = total_shares
            current["sellableShares"] += projected_sellable

        rows: list[dict] = []
        for symbol, row in grouped.items():
            pending = pending_sell.get(symbol, [])
            frozen = sum(o.shares for o in pending)
            display_sellable = max(0, row["sellableShares"] - frozen)
            price = self.price_resolver.resolve_for_market_status(
                symbol,
                trade_date,
                market_status=market_session.market_status,
                fallback=row["lastPrice"],
                shares=row["shares"],
            )
            quote_price = price.close_price
            previous_close = price.previous_close or row["costPrice"]
            market_value = price.market_value
            trade_summary = trade_totals.get(symbol)
            position_cost_amount = row["costAmount"]
            if trade_summary is not None:
                net_shares = trade_summary["buyShares"] - trade_summary["sellShares"]
                if net_shares == row["shares"] and row["shares"] > 0:
                    position_cost_amount = (
                        trade_summary["buyAmount"] - trade_summary["sellAmount"]
                    )

            diluted_cost_price = (
                position_cost_amount / row["shares"] if row["shares"] > 0 else 0.0
            )
            pnl = market_value - position_cost_amount
            ret = 0.0 if position_cost_amount == 0 else pnl / abs(position_cost_amount)
            today_pnl = (quote_price - previous_close) * row["shares"]
            today_return = 0.0 if previous_close == 0 else (quote_price - previous_close) / previous_close

            rows.append(
                {
                    "symbol": row["symbol"],
                    "name": row["name"] or (trade_summary["name"] if trade_summary else symbol),
                    "shares": row["shares"],
                    "sellableShares": display_sellable,
                    "frozenSellShares": frozen,
                    "costPrice": diluted_cost_price,
                    "lastPrice": quote_price,
                    "todayPnl": today_pnl,
                    "todayReturn": today_return,
                    "marketValue": market_value,
                    "pnl": pnl,
                    "returnRate": ret,
                }
            )
        rows.sort(key=lambda item: item["marketValue"], reverse=True)
        return rows

    def get_closed_positions(self, user_id: str) -> list[dict]:
        self._sync_visible_day_order_statuses(user_id)
        lots = self.portfolio_repo.all_lots(user_id)
        if not lots:
            return []

        remaining_by_symbol: dict[str, int] = defaultdict(int)
        opened_at_by_symbol: dict[str, datetime] = {}
        closed_at_by_symbol: dict[str, datetime] = {}
        lot_name_by_symbol: dict[str, str] = {}

        for lot in lots:
            remaining_by_symbol[lot.symbol] += lot.remaining_shares
            if lot.symbol_name and lot.symbol not in lot_name_by_symbol:
                lot_name_by_symbol[lot.symbol] = lot.symbol_name

            existing_opened_at = opened_at_by_symbol.get(lot.symbol)
            if existing_opened_at is None or lot.opened_at < existing_opened_at:
                opened_at_by_symbol[lot.symbol] = lot.opened_at

            if lot.closed_at is not None:
                existing_closed_at = closed_at_by_symbol.get(lot.symbol)
                if existing_closed_at is None or lot.closed_at > existing_closed_at:
                    closed_at_by_symbol[lot.symbol] = lot.closed_at

        closed_symbols = {
            symbol
            for symbol, remaining_shares in remaining_by_symbol.items()
            if remaining_shares == 0
        }
        if not closed_symbols:
            return []

        trade_summary: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "name": "",
                "buyShares": 0,
                "buyAmount": 0.0,
                "sellShares": 0,
                "sellAmount": 0.0,
                "costBasisAmount": 0.0,
                "realizedPnl": 0.0,
                "lastSellAt": None,
            }
        )
        trade_stmt = (
            select(ExecutionTrade, InstructionOrder)
            .join(InstructionOrder, InstructionOrder.id == ExecutionTrade.order_id)
            .where(ExecutionTrade.user_id == user_id)
            .order_by(ExecutionTrade.fill_time.asc(), ExecutionTrade.id.asc())
        )
        for trade, order in self.session.execute(trade_stmt).all():
            if trade.symbol not in closed_symbols:
                continue

            current = trade_summary[trade.symbol]
            if not current["name"]:
                current["name"] = order.symbol_name or trade.symbol

            amount = trade.fill_price * trade.shares
            if trade.side == OrderSide.BUY:
                current["buyShares"] += trade.shares
                current["buyAmount"] += amount
                continue

            current["sellShares"] += trade.shares
            current["sellAmount"] += amount
            current["costBasisAmount"] += trade.cost_basis_amount
            current["realizedPnl"] += trade.realized_pnl

            existing_last_sell_at = current["lastSellAt"]
            if existing_last_sell_at is None or trade.fill_time > existing_last_sell_at:
                current["lastSellAt"] = trade.fill_time

        rows: list[dict] = []
        for symbol in closed_symbols:
            summary = trade_summary.get(symbol)
            if not summary or summary["buyShares"] <= 0 or summary["sellShares"] <= 0:
                continue

            opened_at = opened_at_by_symbol.get(symbol)
            closed_at = closed_at_by_symbol.get(symbol) or summary["lastSellAt"]
            if opened_at is None or closed_at is None:
                continue

            cost_basis_amount = (
                summary["costBasisAmount"]
                if summary["costBasisAmount"] > 0
                else summary["buyAmount"]
            )
            rows.append(
                {
                    "symbol": symbol,
                    "name": summary["name"] or lot_name_by_symbol.get(symbol, symbol),
                    "openedAt": format_dt(opened_at),
                    "closedAt": format_dt(closed_at),
                    "buyShares": summary["buyShares"],
                    "sellShares": summary["sellShares"],
                    "buyPrice": (
                        summary["buyAmount"] / summary["buyShares"]
                        if summary["buyShares"] > 0
                        else 0.0
                    ),
                    "sellPrice": (
                        summary["sellAmount"] / summary["sellShares"]
                        if summary["sellShares"] > 0
                        else 0.0
                    ),
                    "realizedPnl": summary["realizedPnl"],
                    "returnRate": (
                        summary["realizedPnl"] / cost_basis_amount
                        if cost_basis_amount > 0
                        else 0.0
                    ),
                }
            )

        rows.sort(key=lambda item: (item["closedAt"], item["symbol"]), reverse=True)
        return rows

    def get_pending_orders(self, user_id: str) -> list[dict]:
        self._sync_visible_day_order_statuses(user_id)
        rows = self.order_repo.list_orders(user_id, statuses=[
            OrderStatus.confirmed,
            OrderStatus.pending,
            OrderStatus.triggered,
            OrderStatus.filled,
            OrderStatus.cancelled,
            OrderStatus.expired,
            OrderStatus.rejected,
        ])
        output: list[dict] = []
        for row in rows:
            events = sorted(row.events, key=lambda e: e.event_time)
            trades = sorted(row.trades, key=lambda t: t.fill_time)
            can_delete = row.status in {
                OrderStatus.confirmed,
                OrderStatus.pending,
                OrderStatus.triggered,
            } and len(trades) == 0
            output.append(
                {
                    "id": row.id,
                    "tradeDate": row.trade_date,
                    "symbol": row.symbol,
                    "name": row.symbol_name or row.symbol,
                    "side": row.side.value,
                    "orderPrice": row.limit_price,
                    "lots": row.lots,
                    "shares": row.shares,
                    "validity": row.validity.value,
                    "status": row.status.value,
                    "statusMessage": row.status_reason or "",
                    "updatedAt": format_dt(row.updated_at),
                    "canDelete": can_delete,
                    "detail": {
                        "orderText": f"{row.trade_date},{row.symbol},{row.side.value},{row.limit_price:.2f},{row.lots},{row.validity.value}",
                        "transitions": [{"at": format_dt(e.event_time), "status": e.event_type.value, "message": e.message} for e in events],
                        "fillPrice": trades[0].fill_price if trades else None,
                        "fillTime": format_dt(trades[0].fill_time) if trades else None,
                    },
                }
            )
        return output

    def get_history(self, user_id: str) -> list[dict]:
        stmt = (
            select(ExecutionTrade, InstructionOrder)
            .join(InstructionOrder, InstructionOrder.id == ExecutionTrade.order_id)
            .where(ExecutionTrade.user_id == user_id)
            .order_by(ExecutionTrade.fill_time.desc())
        )
        rows: list[dict] = []
        for trade, order in self.session.execute(stmt).all():
            rows.append(
                {
                    "id": trade.id,
                    "time": format_dt(trade.fill_time),
                    "fillTime": to_market_iso(trade.fill_time),
                    "symbol": trade.symbol,
                    "name": order.symbol_name or trade.symbol,
                    "side": trade.side.value,
                    "orderPrice": trade.order_price,
                    "fillPrice": trade.fill_price,
                    "lots": trade.lots,
                    "shares": trade.shares,
                }
            )
        return rows

    def get_calendar(self, user_id: str) -> list[dict]:
        self.settlement.ensure_session_snapshot(user_id, market_clock.get_session())
        return [
            {
                "date": row.trade_date,
                "dailyPnl": row.daily_pnl,
                "dailyReturn": row.daily_return,
                "tradeCount": row.trade_count,
            }
            for row in self.pnl_repo.list_calendar_rows(user_id, final_only=True)
        ]

    def get_daily_detail(self, user_id: str, date: str) -> list[dict]:
        market_session = market_clock.get_session()
        current_snapshot = self.settlement.ensure_session_snapshot(user_id, market_session)
        if date == market_session.trade_date and current_snapshot is not None:
            return [
                {
                    "symbol": row["symbol"],
                    "name": row["symbolName"],
                    "openingShares": row["openingShares"],
                    "closingShares": row["closingShares"],
                    "buyShares": row["buyShares"],
                    "sellShares": row["sellShares"],
                    "buyPrice": row["buyPrice"],
                    "sellPrice": row["sellPrice"],
                    "openPrice": row["openPrice"],
                    "closePrice": row["closePrice"],
                    "dailyPnl": row["dailyPnl"],
                    "dailyReturn": row["dailyReturn"],
                }
                for row in current_snapshot["details"]
            ]

        rows = self.pnl_repo.list_detail_rows(user_id, date)
        result = []
        for r in rows:
            result.append(
                {
                    "symbol": r.symbol,
                    "name": r.symbol_name or r.symbol,
                    "openingShares": r.opening_shares,
                    "closingShares": r.closing_shares,
                    "buyShares": r.buy_shares,
                    "sellShares": r.sell_shares,
                    "buyPrice": r.buy_price,
                    "sellPrice": r.sell_price,
                    "openPrice": r.open_price,
                    "closePrice": r.close_price,
                    "dailyPnl": r.daily_pnl,
                    "dailyReturn": r.daily_return,
                }
            )
        return result


class OrderService:
    def __init__(self, session: Session):
        self.session = session
        self.order_repo = OrderRepository(session)

    def delete_order(self, user_id: str, order_id: str) -> str:
        order = self.order_repo.get_order(order_id)
        if not order or order.user_id != user_id:
            raise ValueError("委托不存在")
        if order.status == OrderStatus.filled or len(order.trades) > 0:
            raise ValueError("已成交委托不可撤单")
        if order.status not in {
            OrderStatus.confirmed,
            OrderStatus.pending,
            OrderStatus.triggered,
        }:
            raise ValueError("当前状态不可撤单")

        self.order_repo.update_order_status(order, status="cancelled", status_reason="用户撤单")
        self.order_repo.add_event(order.id, "cancelled", "用户撤单")
        return order_id


class TradingService:
    def __init__(self, session: Session):
        self.session = session
        self.order_repo = OrderRepository(session)
        self.portfolio_repo = PortfolioRepository(session)
        self.market_repo = MarketDataRepository(session)
        self.quote_service = QuoteService(session)
        self.pnl_service = PnlService(session)
        self.pnl_repo = PnlRepository(session)
        self.settlement = SettlementService(session)

    def _backfill_unfinalized_trade_dates(self, user_id: str, current_trade_date: str) -> None:
        self.settlement.backfill_pending_history(user_id, current_trade_date)

    def _backfill_missing_previous_trade_date(self, user_id: str, current_trade_date: str) -> bool:
        return self.settlement.backfill_missing_previous_trade_date(
            user_id, current_trade_date
        )

    def _mark_confirmed_pending(self, user_id: str, trade_date: str) -> None:
        for order in self.order_repo.list_confirmed_orders(user_id, trade_date):
            self.order_repo.update_order_status(order, status="pending", status_reason="等待触发")
            self.order_repo.add_event(order.id, "pending", "等待触发")

    def _reject_sell_conflicts(self, user_id: str, trade_date: str) -> None:
        orders = self.order_repo.list_conflict_sell_orders(user_id, trade_date)
        availability = self.portfolio_repo.get_available_sellable_shares(
            user_id, trade_date
        )
        reserved: dict[str, int] = defaultdict(int)
        for order in orders:
            reserved_shares = reserved.get(order.symbol, 0)
            sellable = availability.sellable_by_symbol.get(order.symbol, 0)
            available = max(0, sellable - reserved_shares)
            if order.shares > available:
                message = "受 T+1 限制不可卖" if sellable == 0 else "卖单与其他挂单冲突，仓位已被占用"
                self.order_repo.update_order_status(order, status="rejected", status_reason=message)
                self.order_repo.add_event(order.id, "rejected", message)
                continue
            reserved[order.symbol] = reserved_shares + order.shares

    def _expire_day_orders(self, user_id: str, trade_date: str) -> None:
        self.settlement.expire_day_orders(user_id, trade_date)

    def _fill_buy(self, user_id: str, order: InstructionOrder, price: float) -> None:
        available = self.portfolio_repo.cash_balance(user_id)
        amount = price * order.shares
        if available < amount:
            self.order_repo.update_order_status(order, status="rejected", status_reason="资金不足")
            self.order_repo.add_event(order.id, "rejected", "资金不足")
            return

        self.order_repo.add_event(order.id, "triggered", "盘中价格达到买入条件")
        cash_after = available - amount
        open_shares = sum(l.remaining_shares for l in self.portfolio_repo.open_lots(user_id, order.symbol))
        trade = self.order_repo.create_trade(
            user_id=user_id,
            order_id=order.id,
            symbol=order.symbol,
            side=order.side.value,
            order_price=order.limit_price,
            fill_price=price,
            cost_basis_amount=amount,
            realized_pnl=0.0,
            lots=order.lots,
            shares=order.shares,
            fill_time=market_now(),
            cash_after=cash_after,
            position_after=open_shares + order.shares,
        )
        self.portfolio_repo.create_position_lot(
            user_id=user_id,
            symbol=order.symbol,
            symbol_name=order.symbol_name,
            opened_order_id=order.id,
            opened_trade_id=trade.id,
            opened_date=order.trade_date,
            opened_at=trade.fill_time,
            cost_price=price,
            original_shares=order.shares,
            remaining_shares=order.shares,
            sellable_shares=0,
        )
        self.portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=trade.fill_time,
            entry_type="BUY",
            amount=-amount,
            reference_id=order.id,
            reference_type="InstructionOrder",
        )
        self.order_repo.add_event(order.id, "filled", f"按 {price:.2f} 成交")
        self.order_repo.update_order_status(order, status="filled", status_reason="成交完成", triggered_at=trade.fill_time, filled_at=trade.fill_time)

    def _fill_sell(
        self,
        user_id: str,
        order: InstructionOrder,
        price: float,
        trade_date: str,
    ) -> None:
        availability = self.portfolio_repo.get_available_sellable_shares(
            user_id, trade_date, exclude_order_id=order.id
        )
        available = availability.available_by_symbol.get(order.symbol, 0)
        if available < order.shares:
            message = "仓位已被其他卖单占用" if available == 0 else "卖单与其他挂单冲突，仓位已被占用"
            self.order_repo.update_order_status(order, status="rejected", status_reason=message)
            self.order_repo.add_event(order.id, "rejected", message)
            return

        lots = [lot for lot in self.portfolio_repo.open_lots(user_id, order.symbol) if lot.sellable_shares > 0]
        sellable = sum(l.sellable_shares for l in lots)
        if sellable < order.shares:
            message = "受 T+1 限制不可卖" if sellable == 0 else "可卖数量不足"
            self.order_repo.update_order_status(order, status="rejected", status_reason=message)
            self.order_repo.add_event(order.id, "rejected", message)
            return

        self.order_repo.add_event(order.id, "triggered", "盘中价格达到卖出条件")
        remaining = order.shares
        consumed_cost = 0.0
        for lot in lots:
            if remaining <= 0:
                break
            consumed = min(lot.sellable_shares, remaining)
            remaining -= consumed
            consumed_cost += consumed * lot.cost_price
            self.portfolio_repo.update_lot(
                lot,
                remaining_shares=lot.remaining_shares - consumed,
                sellable_shares=lot.sellable_shares - consumed,
                closed_at=market_now(),
            )

        available_cash = self.portfolio_repo.cash_balance(user_id)
        amount = price * order.shares
        cash_after = available_cash + amount
        realized = amount - consumed_cost
        position_after = sum(l.remaining_shares for l in self.portfolio_repo.open_lots(user_id, order.symbol))
        trade = self.order_repo.create_trade(
            user_id=user_id,
            order_id=order.id,
            symbol=order.symbol,
            side=order.side.value,
            order_price=order.limit_price,
            fill_price=price,
            cost_basis_amount=consumed_cost,
            realized_pnl=realized,
            lots=order.lots,
            shares=order.shares,
            fill_time=market_now(),
            cash_after=cash_after,
            position_after=position_after,
        )
        self.portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=trade.fill_time,
            entry_type="SELL",
            amount=amount,
            reference_id=order.id,
            reference_type="InstructionOrder",
        )
        self.order_repo.add_event(order.id, "filled", f"按 {price:.2f} 成交")
        self.order_repo.update_order_status(order, status="filled", status_reason="成交完成", triggered_at=trade.fill_time, filled_at=trade.fill_time)

    def _tracked_symbols(self, user_id: str, trade_date: str) -> list[str]:
        active = self.order_repo.list_pending_orders(user_id, trade_date)
        position_symbols = [l.symbol for l in self.portfolio_repo.open_lots(user_id)]
        start, end = trade_date_bounds(trade_date)
        stmt = select(ExecutionTrade.symbol).where(
            ExecutionTrade.user_id == user_id,
            ExecutionTrade.fill_time >= start,
            ExecutionTrade.fill_time <= end,
        )
        traded_symbols = list(self.session.scalars(stmt).all())
        symbols = sorted(set([o.symbol for o in active] + position_symbols + traded_symbols))
        return symbols

    async def _refresh_realtime_quotes(self, user_id: str, trade_date: str) -> None:
        symbols = self._tracked_symbols(user_id, trade_date)
        if symbols:
            await self.quote_service.fetch_and_store_quotes(symbols)

    def _get_quote_price(self, symbol: str, trade_date: str) -> float | None:
        quote = self.market_repo.latest_intraday_quote(to_quote_symbol(symbol), trade_date)
        return quote.price if quote else None

    async def _process_orders(self, user_id: str, trade_date: str) -> int:
        orders = self.order_repo.list_pending_orders(user_id, trade_date)
        processed = 0
        for order in orders:
            quote_price = self._get_quote_price(order.symbol, trade_date)
            if quote_price is None or quote_price <= 0:
                continue
            should_buy = order.side == OrderSide.BUY and quote_price <= order.limit_price
            should_sell = order.side == OrderSide.SELL and quote_price >= order.limit_price
            if not should_buy and not should_sell:
                continue
            if order.side == OrderSide.BUY:
                self._fill_buy(user_id, order, min(quote_price, order.limit_price))
            else:
                self._fill_sell(
                    user_id,
                    order,
                    max(quote_price, order.limit_price),
                    trade_date,
                )
            processed += 1
        return processed

    async def _settle_close(
        self, user_id: str, trade_date: str, *, force_recompute: bool = False
    ) -> None:
        await self._refresh_realtime_quotes(user_id, trade_date)
        self.settlement.ensure_final_snapshot(
            user_id,
            trade_date,
            refresh_quotes=False,
            source="close_settlement",
            force_recompute=force_recompute,
        )

    async def tick(self, user_id: str, *, session_info=None, phase_changed: bool = False) -> int:
        session_info = session_info or market_clock.get_session()
        self._backfill_unfinalized_trade_dates(user_id, session_info.trade_date)
        previous_trade_date_backfilled = self._backfill_missing_previous_trade_date(
            user_id, session_info.trade_date
        )
        if session_info.market_status in {"weekend", "holiday"}:
            return 0
        self.portfolio_repo.unlock_previous_lots(user_id, session_info.trade_date)
        self._mark_confirmed_pending(user_id, session_info.trade_date)
        self._reject_sell_conflicts(user_id, session_info.trade_date)

        if session_info.market_status == "trading":
            await self._refresh_realtime_quotes(user_id, session_info.trade_date)
            processed = await self._process_orders(user_id, session_info.trade_date)
            self.pnl_service.recompute_daily_pnl(
                user_id,
                session_info.trade_date,
                use_realtime=True,
                is_final=False,
                persist=False,
            )
            return processed

        if session_info.market_status == "lunch_break":
            self.pnl_service.recompute_daily_pnl(
                user_id,
                session_info.trade_date,
                use_realtime=True,
                is_final=False,
                persist=True,
            )
            return 0

        if session_info.market_status == "closed":
            await self._settle_close(
                user_id,
                session_info.trade_date,
                force_recompute=previous_trade_date_backfilled,
            )
            return 0

        return 0


@dataclass
class EngineState:
    running: bool = False
    task: asyncio.Task | None = None
    lock: asyncio.Lock = asyncio.Lock()
    last_session_key: str | None = None


ENGINE_STATE = EngineState()


async def run_engine_tick_once() -> int:
    async with ENGINE_STATE.lock:
        session_info = market_clock.get_session()
        session_key = f"{session_info.trade_date}:{session_info.market_status}"
        phase_changed = session_key != ENGINE_STATE.last_session_key
        with session_scope() as session:
            user_ids = UserRepository(session).list_user_ids()
        processed = 0
        for user_id in user_ids:
            with session_scope() as session:
                service = TradingService(session)
                processed += await service.tick(
                    user_id,
                    session_info=session_info,
                    phase_changed=phase_changed,
                )
        ENGINE_STATE.last_session_key = session_key
        return processed


async def _engine_loop() -> None:
    while ENGINE_STATE.running:
        try:
            await run_engine_tick_once()
        except Exception as exc:  # pragma: no cover
            print(f"[engine] tick failed: {exc}")
        await asyncio.sleep(engine_sleep_seconds())


async def start_engine_if_needed() -> None:
    if not settings.engine_enabled:
        return
    if ENGINE_STATE.running:
        return
    ENGINE_STATE.running = True
    ENGINE_STATE.task = asyncio.create_task(_engine_loop())


async def stop_engine_if_needed() -> None:
    if not ENGINE_STATE.running:
        return
    ENGINE_STATE.running = False
    ENGINE_STATE.last_session_key = None
    task = ENGINE_STATE.task
    ENGINE_STATE.task = None
    if task:
        task.cancel()
        try:
            await task
        except BaseException:
            pass
