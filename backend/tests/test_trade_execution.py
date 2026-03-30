from __future__ import annotations

import asyncio
from datetime import datetime

from app.config import settings
from app.db import session_scope
from app.market import market_clock
from app.repositories import MarketDataRepository, OrderRepository, PortfolioRepository
from app.services import TradingService
from app.user_service import UserService
from tests.helpers import create_filled_buy_position


def test_tick_buy_fill_uses_execution_trade_cash_reference_and_actual_fill_date() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T10:00:00+08:00"

    try:
        with session_scope() as session:
            user_id = UserService(session).create_user(
                name="tick-buy-user", initial_cash=100000
            ).id
            order_repo = OrderRepository(session)
            portfolio_repo = PortfolioRepository(session)
            market_repo = MarketDataRepository(session)

            order = order_repo.create_order(
                user_id=user_id,
                trade_date="2026-03-24",
                symbol="000001",
                symbol_name="平安银行",
                side="BUY",
                limit_price=10.0,
                lots=1,
                validity="GTC",
            )
            market_repo.append_intraday_quote(
                {
                    "symbol": "sz000001",
                    "name": "平安银行",
                    "trade_date": "2026-03-25",
                    "price": 9.8,
                    "open": 9.9,
                    "previousClose": 10.0,
                    "high": 10.0,
                    "low": 9.8,
                    "quoted_at": datetime.strptime(
                        "2026-03-25 10:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                    "source": "test",
                }
            )

            processed = asyncio.run(
                TradingService(session).tick(
                    user_id,
                    session_info=market_clock.get_session(),
                    phase_changed=False,
                )
            )

            filled_order = order_repo.list_orders(user_id)[0]
            trade = filled_order.trades[0]
            latest_cash = portfolio_repo.latest_cash(user_id)
            lots = portfolio_repo.open_lots(user_id, "000001")

            assert processed == 1
            assert filled_order.id == order.id
            assert filled_order.status.value == "filled"
            assert trade.order_id == order.id
            assert latest_cash is not None
            assert latest_cash.reference_id == trade.id
            assert latest_cash.reference_type == "ExecutionTrade"
            assert latest_cash.entry_type.value == "BUY"
            assert len(lots) == 1
            assert lots[0].opened_date == "2026-03-25"
            assert lots[0].opened_trade_id == trade.id
    finally:
        settings.market_now_override = previous_override


def test_tick_sell_fill_uses_execution_trade_cash_reference() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T10:00:00+08:00"

    try:
        with session_scope() as session:
            user_id = UserService(session).create_user(
                name="tick-sell-user", initial_cash=100000
            ).id
            order_repo = OrderRepository(session)
            portfolio_repo = PortfolioRepository(session)
            market_repo = MarketDataRepository(session)

            buy_fill_time = datetime.strptime(
                "2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S"
            )
            create_filled_buy_position(
                order_repo=order_repo,
                portfolio_repo=portfolio_repo,
                user_id=user_id,
                trade_date="2026-03-24",
                fill_time=buy_fill_time,
                symbol="000001",
                symbol_name="平安银行",
                price=10.0,
                lots=1,
                sellable_shares=100,
            )

            sell_order = order_repo.create_order(
                user_id=user_id,
                trade_date="2026-03-24",
                symbol="000001",
                symbol_name="平安银行",
                side="SELL",
                limit_price=11.0,
                lots=1,
                validity="GTC",
            )
            market_repo.append_intraday_quote(
                {
                    "symbol": "sz000001",
                    "name": "平安银行",
                    "trade_date": "2026-03-25",
                    "price": 11.2,
                    "open": 11.0,
                    "previousClose": 10.8,
                    "high": 11.2,
                    "low": 10.9,
                    "quoted_at": datetime.strptime(
                        "2026-03-25 10:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                    "source": "test",
                }
            )

            processed = asyncio.run(
                TradingService(session).tick(
                    user_id,
                    session_info=market_clock.get_session(),
                    phase_changed=False,
                )
            )

            orders = {row.id: row for row in order_repo.list_orders(user_id)}
            filled_sell_order = orders[sell_order.id]
            sell_trade = filled_sell_order.trades[0]
            latest_cash = portfolio_repo.latest_cash(user_id)

            assert processed == 1
            assert filled_sell_order.status.value == "filled"
            assert sell_trade.order_id == sell_order.id
            assert latest_cash is not None
            assert latest_cash.reference_id == sell_trade.id
            assert latest_cash.reference_type == "ExecutionTrade"
            assert latest_cash.entry_type.value == "SELL"
            assert portfolio_repo.open_lots(user_id, "000001") == []
    finally:
        settings.market_now_override = previous_override
