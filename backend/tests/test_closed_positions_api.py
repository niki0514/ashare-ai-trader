from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.repositories import OrderRepository, PortfolioRepository, UserRepository
from devtools.schema import reset_db
from app.db import session_scope


TEST_USER_NAME = "closed-position-user"


def reset_database() -> None:
    reset_db()


def test_closed_positions_endpoint_lists_fully_exited_symbols() -> None:
    reset_database()

    with session_scope() as session:
        user_id = UserRepository(session).create(
            name=TEST_USER_NAME, initial_cash=100000
        ).id
        order_repo = OrderRepository(session)
        portfolio_repo = PortfolioRepository(session)

        initial_time = datetime.strptime("2026-03-24 09:00:00", "%Y-%m-%d %H:%M:%S")
        buy_fill_time = datetime.strptime("2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S")
        sell_fill_time = datetime.strptime("2026-03-25 10:05:00", "%Y-%m-%d %H:%M:%S")
        portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=initial_time,
            entry_type="INITIAL",
            amount=100000,
            reference_type="Bootstrap",
        )

        buy_order = order_repo.create_order(
            user_id=user_id,
            trade_date="2026-03-24",
            symbol="000001",
            symbol_name="平安银行",
            side="BUY",
            limit_price=10.0,
            lots=1,
            validity="DAY",
            status="filled",
            status_reason="成交完成",
            created_at=buy_fill_time,
        )
        buy_trade = order_repo.create_trade(
            user_id=user_id,
            order_id=buy_order.id,
            symbol="000001",
            side="BUY",
            order_price=10.0,
            fill_price=10.0,
            cost_basis_amount=1000.0,
            realized_pnl=0.0,
            lots=1,
            shares=100,
            fill_time=buy_fill_time,
            cash_after=99000.0,
            position_after=100,
        )
        portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=buy_fill_time,
            entry_type="BUY",
            amount=-1000.0,
            reference_id=buy_trade.id,
            reference_type="ExecutionTrade",
        )
        lot = portfolio_repo.create_position_lot(
            user_id=user_id,
            symbol="000001",
            symbol_name="平安银行",
            opened_order_id=buy_order.id,
            opened_trade_id=buy_trade.id,
            opened_date="2026-03-24",
            opened_at=buy_fill_time,
            cost_price=10.0,
            original_shares=100,
            remaining_shares=100,
            sellable_shares=100,
        )

        sell_order = order_repo.create_order(
            user_id=user_id,
            trade_date="2026-03-25",
            symbol="000001",
            symbol_name="平安银行",
            side="SELL",
            limit_price=11.2,
            lots=1,
            validity="DAY",
            status="filled",
            status_reason="成交完成",
            created_at=sell_fill_time,
        )
        sell_trade = order_repo.create_trade(
            user_id=user_id,
            order_id=sell_order.id,
            symbol="000001",
            side="SELL",
            order_price=11.2,
            fill_price=11.2,
            cost_basis_amount=1000.0,
            realized_pnl=120.0,
            lots=1,
            shares=100,
            fill_time=sell_fill_time,
            cash_after=100120.0,
            position_after=0,
        )
        portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=sell_fill_time,
            entry_type="SELL",
            amount=1120.0,
            reference_id=sell_trade.id,
            reference_type="ExecutionTrade",
        )
        portfolio_repo.update_lot(
            lot,
            remaining_shares=0,
            sellable_shares=0,
            closed_at=sell_fill_time,
        )

    with TestClient(app) as client:
        response = client.get("/api/positions/closed", headers={"x-user-id": user_id})

    assert response.status_code == 200
    assert response.json() == {
        "rows": [
            {
                "symbol": "000001",
                "name": "平安银行",
                "openedAt": "2026-03-24 10:00:00",
                "closedAt": "2026-03-25 10:05:00",
                "buyShares": 100,
                "sellShares": 100,
                "buyPrice": 10.0,
                "sellPrice": 11.2,
                "realizedPnl": 120.0,
                "returnRate": 0.12,
            }
        ]
    }
