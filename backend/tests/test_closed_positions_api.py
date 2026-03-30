from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.db import session_scope
from app.main import app
from app.repositories import OrderRepository, PortfolioRepository, UserRepository
from tests.helpers import create_filled_buy_position, create_filled_sell_execution


TEST_USER_NAME = "closed-position-user"


def test_closed_positions_endpoint_lists_fully_exited_symbols() -> None:

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
        create_filled_sell_execution(
            order_repo=order_repo,
            portfolio_repo=portfolio_repo,
            user_id=user_id,
            trade_date="2026-03-25",
            fill_time=sell_fill_time,
            symbol="000001",
            symbol_name="平安银行",
            price=11.2,
            lots=1,
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
