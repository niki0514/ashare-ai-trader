from __future__ import annotations

from datetime import datetime

import pytest
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


def test_closed_positions_endpoint_keeps_multiple_cycles_for_same_symbol() -> None:
    with session_scope() as session:
        user_id = UserRepository(session).create(
            name=f"{TEST_USER_NAME}-repeat", initial_cash=100000
        ).id
        order_repo = OrderRepository(session)
        portfolio_repo = PortfolioRepository(session)

        initial_time = datetime.strptime("2026-03-24 09:00:00", "%Y-%m-%d %H:%M:%S")
        first_buy_time = datetime.strptime("2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S")
        first_sell_time = datetime.strptime("2026-03-25 10:05:00", "%Y-%m-%d %H:%M:%S")
        second_buy_time = datetime.strptime("2026-03-26 10:10:00", "%Y-%m-%d %H:%M:%S")
        second_sell_time = datetime.strptime("2026-03-27 10:15:00", "%Y-%m-%d %H:%M:%S")
        third_buy_time = datetime.strptime("2026-03-30 10:20:00", "%Y-%m-%d %H:%M:%S")
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
            fill_time=first_buy_time,
            symbol="000021",
            symbol_name="深科技",
            price=10.0,
            lots=1,
            sellable_shares=100,
        )
        create_filled_sell_execution(
            order_repo=order_repo,
            portfolio_repo=portfolio_repo,
            user_id=user_id,
            trade_date="2026-03-25",
            fill_time=first_sell_time,
            symbol="000021",
            symbol_name="深科技",
            price=11.0,
            lots=1,
        )
        create_filled_buy_position(
            order_repo=order_repo,
            portfolio_repo=portfolio_repo,
            user_id=user_id,
            trade_date="2026-03-26",
            fill_time=second_buy_time,
            symbol="000021",
            symbol_name="深科技",
            price=12.0,
            lots=2,
            sellable_shares=200,
        )
        create_filled_sell_execution(
            order_repo=order_repo,
            portfolio_repo=portfolio_repo,
            user_id=user_id,
            trade_date="2026-03-27",
            fill_time=second_sell_time,
            symbol="000021",
            symbol_name="深科技",
            price=13.0,
            lots=2,
        )
        create_filled_buy_position(
            order_repo=order_repo,
            portfolio_repo=portfolio_repo,
            user_id=user_id,
            trade_date="2026-03-30",
            fill_time=third_buy_time,
            symbol="000021",
            symbol_name="深科技",
            price=14.0,
            lots=1,
            sellable_shares=0,
        )

    with TestClient(app) as client:
        response = client.get("/api/positions/closed", headers={"x-user-id": user_id})

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 2

    assert rows[0] == {
        "symbol": "000021",
        "name": "深科技",
        "openedAt": "2026-03-26 10:10:00",
        "closedAt": "2026-03-27 10:15:00",
        "buyShares": 200,
        "sellShares": 200,
        "buyPrice": 12.0,
        "sellPrice": 13.0,
        "realizedPnl": 200.0,
        "returnRate": pytest.approx(200.0 / 2400.0),
    }
    assert rows[1] == {
        "symbol": "000021",
        "name": "深科技",
        "openedAt": "2026-03-24 10:00:00",
        "closedAt": "2026-03-25 10:05:00",
        "buyShares": 100,
        "sellShares": 100,
        "buyPrice": 10.0,
        "sellPrice": 11.0,
        "realizedPnl": 100.0,
        "returnRate": pytest.approx(0.1),
    }
