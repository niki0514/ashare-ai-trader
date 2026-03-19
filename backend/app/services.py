from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .db import session_scope
from .market import market_clock
from .models import DailyPnlDetail, ExecutionTrade, InstructionOrder, OrderSide, OrderStatus, PositionLot, PositionStatus, User
from .quote_client import TencentQuoteClient, to_quote_symbol
from .repositories import (
    MarketDataRepository,
    OrderRepository,
    PnlRepository,
    PortfolioRepository,
    UserRepository,
)
from .seed_data import SEED_CLOSE_PRICES, SEED_TRADES, event_times_for_trade, parse_trade_time


def format_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def to_iso(value: datetime | None) -> str:
    return (value or datetime.now()).isoformat()


class SeedService:
    def __init__(self, session: Session):
        self.session = session
        self.user_repo = UserRepository(session)
        self.order_repo = OrderRepository(session)
        self.portfolio_repo = PortfolioRepository(session)
        self.market_repo = MarketDataRepository(session)

    def ensure_seed_data(self, user_id: str) -> None:
        user = self.user_repo.get_or_create(user_id, settings.default_user_name, settings.initial_cash)
        if self.order_repo.count_orders(user_id) > 0:
            return

        first_time = parse_trade_time(SEED_TRADES[0].trade_time)
        self.portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=first_time,
            entry_type="INITIAL",
            amount=user.initial_cash,
            balance_after=user.initial_cash,
        )

        current_trade_date: str | None = None
        for seed in SEED_TRADES:
            fill_time = parse_trade_time(seed.trade_time)
            trade_date = fill_time.strftime("%Y-%m-%d")
            if current_trade_date != trade_date:
                current_trade_date = trade_date
                self.portfolio_repo.unlock_previous_lots(user_id, trade_date)

            ts = event_times_for_trade(fill_time)
            order = self.order_repo.create_order(
                user_id=user_id,
                trade_date=trade_date,
                symbol=seed.symbol,
                symbol_name=seed.name,
                side=seed.side,
                limit_price=seed.order_price,
                lots=seed.lots,
                validity="DAY",
                status="filled",
                status_reason="成交完成",
                created_at=ts["created"],
            )
            self.order_repo.add_event(order.id, "confirmed", "已导入待执行", ts["created"])
            self.order_repo.add_event(order.id, "pending", "等待触发", ts["pending"])
            self.order_repo.add_event(order.id, "triggered", f"盘中价格达到{'买入' if seed.side == 'BUY' else '卖出'}条件", ts["triggered"])

            latest_cash = self.portfolio_repo.latest_cash(user_id)
            available_cash = latest_cash.balance_after if latest_cash else 0.0

            if seed.side == "BUY":
                amount = seed.fill_price * seed.shares
                balance_after = available_cash - amount
                open_shares = sum(l.remaining_shares for l in self.portfolio_repo.open_lots(user_id, seed.symbol))
                trade = self.order_repo.create_trade(
                    user_id=user_id,
                    order_id=order.id,
                    symbol=seed.symbol,
                    side=seed.side,
                    order_price=seed.order_price,
                    fill_price=seed.fill_price,
                    cost_basis_amount=amount,
                    realized_pnl=0.0,
                    lots=seed.lots,
                    shares=seed.shares,
                    fill_time=fill_time,
                    cash_after=balance_after,
                    position_after=open_shares + seed.shares,
                )
                self.portfolio_repo.create_position_lot(
                    user_id=user_id,
                    symbol=seed.symbol,
                    symbol_name=seed.name,
                    opened_order_id=order.id,
                    opened_trade_id=trade.id,
                    opened_date=trade_date,
                    opened_at=fill_time,
                    cost_price=seed.fill_price,
                    original_shares=seed.shares,
                    remaining_shares=seed.shares,
                    sellable_shares=0,
                )
                self.portfolio_repo.add_cash_entry(
                    user_id=user_id,
                    entry_time=fill_time,
                    entry_type="BUY",
                    amount=-amount,
                    balance_after=balance_after,
                    reference_id=order.id,
                    reference_type="InstructionOrder",
                )
            else:
                remaining = seed.shares
                consumed_cost = 0.0
                lots = self.portfolio_repo.open_lots(user_id, seed.symbol)
                for lot in lots:
                    if remaining <= 0:
                        break
                    consumed = min(lot.sellable_shares, remaining)
                    if consumed <= 0:
                        continue
                    remaining -= consumed
                    consumed_cost += consumed * lot.cost_price
                    self.portfolio_repo.update_lot(
                        lot,
                        remaining_shares=lot.remaining_shares - consumed,
                        sellable_shares=max(0, lot.sellable_shares - consumed),
                        closed_at=fill_time,
                    )

                amount = seed.fill_price * seed.shares
                balance_after = available_cash + amount
                open_shares = sum(l.remaining_shares for l in self.portfolio_repo.open_lots(user_id, seed.symbol))
                self.order_repo.create_trade(
                    user_id=user_id,
                    order_id=order.id,
                    symbol=seed.symbol,
                    side=seed.side,
                    order_price=seed.order_price,
                    fill_price=seed.fill_price,
                    cost_basis_amount=consumed_cost,
                    realized_pnl=amount - consumed_cost,
                    lots=seed.lots,
                    shares=seed.shares,
                    fill_time=fill_time,
                    cash_after=balance_after,
                    position_after=open_shares,
                )
                self.portfolio_repo.add_cash_entry(
                    user_id=user_id,
                    entry_time=fill_time,
                    entry_type="SELL",
                    amount=amount,
                    balance_after=balance_after,
                    reference_id=order.id,
                    reference_type="InstructionOrder",
                )

            self.order_repo.add_event(order.id, "filled", f"按 {seed.fill_price:.2f} 成交", ts["filled"])
            self.order_repo.update_order_status(order, status="filled", status_reason="成交完成", triggered_at=fill_time, filled_at=fill_time)

        for lot in self.portfolio_repo.open_lots(user_id):
            lot.sellable_shares = lot.remaining_shares

        sorted_days = sorted(SEED_CLOSE_PRICES.keys())
        for day_idx, trade_date in enumerate(sorted_days):
            day_prices = SEED_CLOSE_PRICES[trade_date]
            for symbol, close_price in day_prices.items():
                prev_close = close_price
                if day_idx > 0:
                    prev_close = SEED_CLOSE_PRICES[sorted_days[day_idx - 1]].get(symbol, close_price)
                self.market_repo.upsert_daily_price(
                    symbol=symbol,
                    symbol_name="深科技" if symbol == "000021" else "航天发展",
                    trade_date=trade_date,
                    close_price=close_price,
                    open_price=close_price,
                    previous_close=prev_close,
                    high_price=close_price,
                    low_price=close_price,
                    is_final=True,
                    source="seed",
                )

        latest_day = sorted_days[-1]
        for symbol, close_price in SEED_CLOSE_PRICES[latest_day].items():
            prev_close = SEED_CLOSE_PRICES[sorted_days[-2]].get(symbol, close_price) if len(sorted_days) > 1 else close_price
            self.market_repo.upsert_quote_snapshot(
                {
                    "symbol": to_quote_symbol(symbol),
                    "name": "深科技" if symbol == "000021" else "航天发展",
                    "price": close_price,
                    "open": close_price,
                    "previousClose": prev_close,
                    "high": close_price,
                    "low": close_price,
                    "updated_at": datetime.strptime(f"{latest_day} 15:00:00", "%Y-%m-%d %H:%M:%S"),
                    "source": "seed",
                }
            )


class QuoteService:
    def __init__(self, session: Session):
        self.session = session
        self.market_repo = MarketDataRepository(session)
        self.quote_client = TencentQuoteClient()

    async def fetch_and_store_quotes(self, symbols: list[str]) -> list[dict]:
        normalized = sorted(set(to_quote_symbol(s) for s in symbols if s))
        rows = await self.quote_client.fetch_quotes(normalized)
        now = datetime.now()
        result: list[dict] = []
        for row in rows:
            saved = self.market_repo.upsert_quote_snapshot(
                {
                    "symbol": row.symbol,
                    "name": row.name,
                    "price": row.price,
                    "open": row.open_price,
                    "previousClose": row.previous_close,
                    "high": row.high_price,
                    "low": row.low_price,
                    "updated_at": row.updated_at or now,
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
                    "updatedAt": saved.updated_at.isoformat(),
                }
            )
        return result

    def get_quotes(self, symbols: list[str] | None = None) -> list[dict]:
        rows = self.market_repo.list_quotes([to_quote_symbol(s) for s in symbols] if symbols else None)
        return [
            {
                "symbol": row.symbol,
                "name": row.symbol_name or row.symbol,
                "price": row.price,
                "open": row.open_price,
                "previousClose": row.previous_close,
                "high": row.high_price,
                "low": row.low_price,
                "updatedAt": row.updated_at.isoformat(),
            }
            for row in rows
        ]

    def latest_updated_at(self) -> str:
        dt = self.market_repo.latest_quote_updated_at()
        return to_iso(dt)


class PnlService:
    def __init__(self, session: Session):
        self.session = session
        self.portfolio_repo = PortfolioRepository(session)
        self.pnl_repo = PnlRepository(session)
        self.market_repo = MarketDataRepository(session)

    def _build_position_snapshot(self, user_id: str, trade_date: str) -> dict[str, dict[str, Any]]:
        end = datetime.strptime(f"{trade_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
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

    def _price_snapshot(self, symbol: str, shares: int, fallback: float, trade_date: str, use_realtime: bool) -> tuple[float, float, float]:
        quote = self.market_repo.get_quote(to_quote_symbol(symbol))
        daily = self.market_repo.latest_daily_price(symbol, trade_date)
        if use_realtime and quote:
            open_price = quote.open_price or daily.open_price if daily else quote.open_price
            close_price = quote.price
        else:
            close_price = daily.close_price if daily else (quote.price if quote else fallback)
            open_price = daily.open_price if daily else (quote.open_price if quote else fallback)
        return open_price or fallback, close_price or fallback, shares * (close_price or fallback)

    def recompute_daily_pnl(self, user_id: str, trade_date: str, *, use_realtime: bool, is_final: bool = False) -> dict:
        as_of_end = datetime.strptime(f"{trade_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        latest_cash = self.portfolio_repo.latest_cash(user_id, before=as_of_end)
        available_cash = latest_cash.balance_after if latest_cash else 0.0

        grouped = self._build_position_snapshot(user_id, trade_date)

        previous_day = self.pnl_repo.previous_daily_pnl(user_id, trade_date)
        first_day = self.pnl_repo.first_daily_pnl(user_id)
        previous_details = {d.symbol: {"shares": d.closing_shares, "price": d.close_price} for d in (previous_day.details if previous_day else [])}

        start = datetime.strptime(f"{trade_date} 00:00:00", "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(f"{trade_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
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
                "realizedPnl": 0.0,
                "costBasisAmount": 0.0,
            }
        )
        for trade in today_trades:
            cur = trade_stats[trade.symbol]
            if not cur["symbolName"]:
                order = self.session.get(InstructionOrder, trade.order_id)
                cur["symbolName"] = (order.symbol_name if order and order.symbol_name else trade.symbol)
            if trade.side == OrderSide.BUY:
                cur["buyShares"] += trade.shares
                cur["buyAmount"] += trade.fill_price * trade.shares
            else:
                cur["sellShares"] += trade.shares
                cur["sellAmount"] += trade.fill_price * trade.shares
                cur["realizedPnl"] += trade.realized_pnl
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
                current["realizedPnl"] = current["sellAmount"] - current["costBasisAmount"]

        detail_symbols = set(grouped.keys()) | set(previous_details.keys()) | set(trade_stats.keys())
        detail_rows: list[dict] = []
        for symbol in sorted(detail_symbols):
            current_holding = grouped.get(symbol)
            previous = previous_details.get(symbol)
            stat = trade_stats.get(symbol)

            closing_shares = current_holding["shares"] if current_holding else 0
            cost_amount = current_holding["costAmount"] if current_holding else 0.0
            fallback_price = (
                current_holding["fallbackPrice"]
                if current_holding
                else (previous["price"] if previous else 0.0)
            )
            open_price, close_price, market_value = self._price_snapshot(symbol, closing_shares, fallback_price, trade_date, use_realtime)

            previous_shares = previous["shares"] if previous else 0
            previous_price = previous["price"] if previous else fallback_price
            buy_shares = stat["buyShares"] if stat else 0
            buy_amount = stat["buyAmount"] if stat else 0.0
            sell_shares = stat["sellShares"] if stat else 0
            sell_amount = stat["sellAmount"] if stat else 0.0
            realized_pnl = stat["realizedPnl"] if stat else 0.0
            realized_cost_basis = stat["costBasisAmount"] if stat else 0.0

            sold_from_previous = max(0, min(previous_shares, sell_shares))
            remaining_previous = max(0, previous_shares - sold_from_previous)
            same_day_bought_remaining = max(0, closing_shares - remaining_previous)

            avg_buy_price = (buy_amount / buy_shares) if buy_shares else 0.0
            avg_sell_price = (sell_amount / sell_shares) if sell_shares else 0.0
            buy_price = (cost_amount / closing_shares) if closing_shares > 0 else ((realized_cost_basis / sell_shares) if sell_shares > 0 else 0.0)

            carried_pnl = remaining_previous * (close_price - previous_price)
            bought_remaining_pnl = same_day_bought_remaining * (close_price - avg_buy_price)
            unrealized_pnl = carried_pnl + bought_remaining_pnl

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
                    "realizedPnl": realized_pnl,
                    "unrealizedPnl": unrealized_pnl,
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
        self.pnl_repo.upsert_daily_pnl(user_id=user_id, trade_date=trade_date, payload=payload, is_final=is_final)
        return payload


class QueryService:
    def __init__(self, session: Session):
        self.session = session
        self.order_repo = OrderRepository(session)
        self.portfolio_repo = PortfolioRepository(session)
        self.pnl_repo = PnlRepository(session)
        self.market_repo = MarketDataRepository(session)
        self.pnl_service = PnlService(session)
        self.quote_service = QuoteService(session)

    def get_dashboard(self, user_id: str) -> dict:
        market_session = market_clock.get_session()
        trade_date = market_session.trade_date
        daily = self.pnl_repo.get_daily_pnl(user_id, trade_date)
        use_intraday_quote = market_session.market_status in {"trading", "lunch_break"}
        if use_intraday_quote:
            self.pnl_service.recompute_daily_pnl(user_id, trade_date, use_realtime=True, is_final=False)
            daily = self.pnl_repo.get_daily_pnl(user_id, trade_date)
        elif not daily:
            self.pnl_service.recompute_daily_pnl(user_id, trade_date, use_realtime=False, is_final=market_session.market_status == "closed")
            daily = self.pnl_repo.get_daily_pnl(user_id, trade_date)

        latest_cash = self.portfolio_repo.latest_cash(user_id)
        open_lots = self.portfolio_repo.open_lots(user_id)
        position_market_value = 0.0
        for lot in open_lots:
            quote = self.market_repo.get_quote(to_quote_symbol(lot.symbol))
            daily_price = self.market_repo.latest_daily_price(lot.symbol, trade_date)
            if use_intraday_quote:
                price = quote.price if quote else (daily_price.close_price if daily_price else lot.cost_price)
            else:
                price = daily_price.close_price if daily_price else (quote.price if quote else lot.cost_price)
            position_market_value += lot.remaining_shares * price

        available_cash = latest_cash.balance_after if latest_cash else 0.0
        total_assets = daily.total_assets if daily else (available_cash + position_market_value)
        daily_pnl = daily.daily_pnl if daily else 0.0
        cumulative_pnl = daily.cumulative_pnl if daily else 0.0

        return {
            "tradeDate": trade_date,
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

    def get_positions(self, user_id: str) -> list[dict]:
        market_session = market_clock.get_session()
        trade_date = market_session.trade_date
        lots = self.portfolio_repo.open_lots(user_id)
        pending_sell = self.portfolio_repo.get_pending_sell_orders_by_symbol(user_id)

        previous_day = self.pnl_repo.previous_daily_pnl(user_id, trade_date)
        previous_close_by_symbol = {d.symbol: d.close_price for d in (previous_day.details if previous_day else [])}

        grouped: dict[str, dict[str, Any]] = {}
        for lot in lots:
            current = grouped.setdefault(
                lot.symbol,
                {
                    "symbol": lot.symbol,
                    "name": lot.symbol_name or lot.symbol,
                    "shares": 0,
                    "sellableShares": 0,
                    "frozenSellShares": 0,
                    "costPrice": 0.0,
                    "lastPrice": lot.cost_price,
                    "todayPnl": 0.0,
                    "todayReturn": 0.0,
                },
            )
            total_shares = current["shares"] + lot.remaining_shares
            if total_shares > 0:
                current["costPrice"] = (
                    current["costPrice"] * current["shares"] + lot.cost_price * lot.remaining_shares
                ) / total_shares
            current["shares"] = total_shares
            current["sellableShares"] += lot.sellable_shares

        rows: list[dict] = []
        use_intraday_quote = market_session.market_status in {"trading", "lunch_break"}
        for symbol, row in grouped.items():
            pending = pending_sell.get(symbol, [])
            frozen = sum(o.shares for o in pending)
            display_sellable = max(0, row["sellableShares"] - frozen)
            quote = self.market_repo.get_quote(to_quote_symbol(symbol))
            daily_price = self.market_repo.latest_daily_price(symbol, trade_date)
            if use_intraday_quote:
                quote_price = quote.price if quote else (daily_price.close_price if daily_price else row["lastPrice"])
                previous_close = quote.previous_close if quote else previous_close_by_symbol.get(symbol, row["costPrice"])
            else:
                quote_price = daily_price.close_price if daily_price else (quote.price if quote else row["lastPrice"])
                previous_close = previous_close_by_symbol.get(symbol, quote_price)

            market_value = row["shares"] * quote_price
            pnl = (quote_price - row["costPrice"]) * row["shares"]
            ret = 0.0 if row["costPrice"] == 0 else pnl / (row["costPrice"] * row["shares"])
            today_pnl = (quote_price - previous_close) * row["shares"]
            today_return = 0.0 if previous_close == 0 else (quote_price - previous_close) / previous_close

            rows.append(
                {
                    **row,
                    "sellableShares": display_sellable,
                    "frozenSellShares": frozen,
                    "lastPrice": quote_price,
                    "todayPnl": today_pnl,
                    "todayReturn": today_return,
                    "marketValue": market_value,
                    "pnl": pnl,
                    "returnRate": ret,
                    "pendingOrders": [
                        {
                            "id": o.id,
                            "side": o.side.value,
                            "price": o.limit_price,
                            "shares": o.shares,
                            "lots": o.lots,
                            "status": o.status.value,
                        }
                        for o in pending
                    ],
                }
            )
        rows.sort(key=lambda item: item["marketValue"], reverse=True)
        return rows

    def get_pending_orders(self, user_id: str) -> list[dict]:
        rows = self.order_repo.list_orders(user_id, statuses=[
            OrderStatus.confirmed,
            OrderStatus.pending,
            OrderStatus.triggered,
            OrderStatus.filled,
            OrderStatus.expired,
            OrderStatus.rejected,
        ])
        output: list[dict] = []
        for row in rows:
            events = sorted(row.events, key=lambda e: e.event_time)
            trades = sorted(row.trades, key=lambda t: t.fill_time)
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
                    "fillTime": trade.fill_time.isoformat(),
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
        rows = self.pnl_repo.list_calendar_rows(user_id)
        today = market_clock.now().date().isoformat()
        result: list[dict] = []
        for row in rows:
            if row.trade_date == today and not row.is_final:
                continue
            result.append(
                {
                    "date": row.trade_date,
                    "dailyPnl": row.daily_pnl,
                    "dailyReturn": row.daily_return,
                    "tradeCount": row.trade_count,
                }
            )
        return result

    def get_daily_detail(self, user_id: str, date: str) -> list[dict]:
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
                    "realizedPnl": r.realized_pnl,
                    "unrealizedPnl": r.unrealized_pnl,
                    "dailyPnl": r.daily_pnl,
                    "dailyReturn": r.daily_return,
                }
            )
        return result


class TradingService:
    def __init__(self, session: Session):
        self.session = session
        self.order_repo = OrderRepository(session)
        self.portfolio_repo = PortfolioRepository(session)
        self.market_repo = MarketDataRepository(session)
        self.quote_service = QuoteService(session)
        self.pnl_service = PnlService(session)
        self.pnl_repo = PnlRepository(session)

    def _mark_confirmed_pending(self, user_id: str, trade_date: str) -> None:
        for order in self.order_repo.list_confirmed_orders(user_id, trade_date):
            self.order_repo.update_order_status(order, status="pending", status_reason="等待触发")
            self.order_repo.add_event(order.id, "pending", "等待触发")

    def _reject_sell_conflicts(self, user_id: str, trade_date: str) -> None:
        orders = self.order_repo.list_conflict_sell_orders(user_id, trade_date)
        availability = self.portfolio_repo.get_available_sellable_shares(user_id)
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
        for order in self.order_repo.list_day_orders_to_expire(user_id, trade_date):
            self.order_repo.update_order_status(order, status="expired", status_reason="当日未触价已失效")
            self.order_repo.add_event(order.id, "expired", "当日未触价已失效")

    def _fill_buy(self, user_id: str, order: InstructionOrder, price: float) -> None:
        latest_cash = self.portfolio_repo.latest_cash(user_id)
        available = latest_cash.balance_after if latest_cash else 0.0
        amount = price * order.shares
        if available < amount:
            self.order_repo.update_order_status(order, status="rejected", status_reason="资金不足")
            self.order_repo.add_event(order.id, "rejected", "资金不足")
            return

        self.order_repo.add_event(order.id, "triggered", "盘中价格达到买入条件")
        balance_after = available - amount
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
            fill_time=datetime.now(),
            cash_after=balance_after,
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
            balance_after=balance_after,
            reference_id=order.id,
            reference_type="InstructionOrder",
        )
        self.order_repo.add_event(order.id, "filled", f"按 {price:.2f} 成交")
        self.order_repo.update_order_status(order, status="filled", status_reason="成交完成", triggered_at=trade.fill_time, filled_at=trade.fill_time)

    def _fill_sell(self, user_id: str, order: InstructionOrder, price: float) -> None:
        availability = self.portfolio_repo.get_available_sellable_shares(user_id, exclude_order_id=order.id)
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
                closed_at=datetime.now(),
            )

        latest_cash = self.portfolio_repo.latest_cash(user_id)
        available_cash = latest_cash.balance_after if latest_cash else 0.0
        amount = price * order.shares
        balance_after = available_cash + amount
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
            fill_time=datetime.now(),
            cash_after=balance_after,
            position_after=position_after,
        )
        self.portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=trade.fill_time,
            entry_type="SELL",
            amount=amount,
            balance_after=balance_after,
            reference_id=order.id,
            reference_type="InstructionOrder",
        )
        self.order_repo.add_event(order.id, "filled", f"按 {price:.2f} 成交")
        self.order_repo.update_order_status(order, status="filled", status_reason="成交完成", triggered_at=trade.fill_time, filled_at=trade.fill_time)

    async def _refresh_realtime_quotes(self, user_id: str, trade_date: str) -> None:
        active = self.order_repo.list_pending_orders(user_id, trade_date)
        position_symbols = [l.symbol for l in self.portfolio_repo.open_lots(user_id)]
        symbols = sorted(set([o.symbol for o in active] + position_symbols))
        if symbols:
            await self.quote_service.fetch_and_store_quotes(symbols)

    def _get_quote_price(self, symbol: str) -> float | None:
        quote = self.market_repo.get_quote(to_quote_symbol(symbol))
        return quote.price if quote else None

    async def _process_orders(self, user_id: str, trade_date: str) -> int:
        orders = self.order_repo.list_pending_orders(user_id, trade_date)
        processed = 0
        for order in orders:
            quote_price = self._get_quote_price(order.symbol)
            if quote_price is None or quote_price <= 0:
                continue
            should_buy = order.side == OrderSide.BUY and quote_price <= order.limit_price
            should_sell = order.side == OrderSide.SELL and quote_price >= order.limit_price
            if not should_buy and not should_sell:
                continue
            if order.side == OrderSide.BUY:
                self._fill_buy(user_id, order, min(quote_price, order.limit_price))
            else:
                self._fill_sell(user_id, order, max(quote_price, order.limit_price))
            processed += 1
        return processed

    def _settle_close(self, user_id: str, trade_date: str) -> None:
        existing = self.pnl_repo.get_daily_pnl(user_id, trade_date)
        if existing and existing.is_final:
            return

        symbols = set()
        symbols.update(l.symbol for l in self.portfolio_repo.open_lots(user_id))
        start = datetime.strptime(f"{trade_date} 00:00:00", "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(f"{trade_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        stmt = select(ExecutionTrade).where(ExecutionTrade.user_id == user_id, ExecutionTrade.fill_time >= start, ExecutionTrade.fill_time <= end)
        for trade in self.session.scalars(stmt).all():
            symbols.add(trade.symbol)

        for symbol in symbols:
            quote = self.market_repo.get_quote(to_quote_symbol(symbol))
            existing_daily = self.market_repo.latest_daily_price(symbol, trade_date)
            close_price = quote.price if quote else (existing_daily.close_price if existing_daily else 0.0)
            if close_price <= 0:
                continue
            open_price = quote.open_price if quote else (existing_daily.open_price if existing_daily else close_price)
            prev_close = quote.previous_close if quote else (existing_daily.previous_close if existing_daily else close_price)
            high = quote.high_price if quote else (existing_daily.high_price if existing_daily else close_price)
            low = quote.low_price if quote else (existing_daily.low_price if existing_daily else close_price)
            self.market_repo.upsert_daily_price(
                symbol=symbol,
                symbol_name=(quote.symbol_name if quote else (existing_daily.symbol_name if existing_daily else symbol)),
                trade_date=trade_date,
                close_price=close_price,
                open_price=open_price,
                previous_close=prev_close,
                high_price=high,
                low_price=low,
                is_final=True,
                source="close_settlement",
            )

        self.pnl_service.recompute_daily_pnl(user_id, trade_date, use_realtime=False, is_final=True)
        self._expire_day_orders(user_id, trade_date)

    async def tick(self, user_id: str) -> int:
        session_info = market_clock.get_session()
        self.portfolio_repo.unlock_previous_lots(user_id, session_info.trade_date)
        self._mark_confirmed_pending(user_id, session_info.trade_date)
        self._reject_sell_conflicts(user_id, session_info.trade_date)

        if session_info.market_status == "trading":
            await self._refresh_realtime_quotes(user_id, session_info.trade_date)
            processed = await self._process_orders(user_id, session_info.trade_date)
            self.pnl_service.recompute_daily_pnl(user_id, session_info.trade_date, use_realtime=True, is_final=False)
            return processed

        if session_info.market_status == "lunch_break":
            self.pnl_service.recompute_daily_pnl(user_id, session_info.trade_date, use_realtime=True, is_final=False)
            return 0

        if session_info.market_status == "closed":
            self._settle_close(user_id, session_info.trade_date)
            return 0

        self.pnl_service.recompute_daily_pnl(user_id, session_info.trade_date, use_realtime=False, is_final=False)
        return 0


@dataclass
class EngineState:
    running: bool = False
    task: asyncio.Task | None = None
    lock: asyncio.Lock = asyncio.Lock()


ENGINE_STATE = EngineState()


async def run_engine_tick_once() -> int:
    async with ENGINE_STATE.lock:
        with session_scope() as session:
            service = TradingService(session)
            processed = await service.tick(settings.default_user_id)
        return processed


async def _engine_loop() -> None:
    while ENGINE_STATE.running:
        try:
            await run_engine_tick_once()
        except Exception as exc:  # pragma: no cover
            print(f"[engine] tick failed: {exc}")
        await asyncio.sleep(settings.quote_poll_seconds)


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
    task = ENGINE_STATE.task
    ENGINE_STATE.task = None
    if task:
        task.cancel()
        try:
            await task
        except BaseException:
            pass
