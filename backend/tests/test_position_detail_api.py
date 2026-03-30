from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.config import settings
from app.db import session_scope
from app.main import app
from app.repositories import MarketDataRepository, OrderRepository, PortfolioRepository
from tests.helpers import create_filled_buy_position


def test_position_detail_endpoint_returns_summary_lots_and_pending_sell_orders() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": "position-detail-user", "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                order_repo = OrderRepository(session)
                market_repo = MarketDataRepository(session)

                first_lot_time = datetime.strptime(
                    "2026-03-20 10:00:00", "%Y-%m-%d %H:%M:%S"
                )
                second_lot_time = datetime.strptime(
                    "2026-03-25 10:00:00", "%Y-%m-%d %H:%M:%S"
                )

                create_filled_buy_position(
                    order_repo=order_repo,
                    portfolio_repo=PortfolioRepository(session),
                    user_id=user_id,
                    trade_date="2026-03-20",
                    fill_time=first_lot_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.0,
                    lots=5,
                )
                create_filled_buy_position(
                    order_repo=order_repo,
                    portfolio_repo=PortfolioRepository(session),
                    user_id=user_id,
                    trade_date="2026-03-25",
                    fill_time=second_lot_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.2,
                    lots=3,
                )
                order_repo.create_order(
                    user_id=user_id,
                    trade_date="2026-03-26",
                    symbol="000001",
                    symbol_name="平安银行",
                    side="SELL",
                    limit_price=11.8,
                    lots=6,
                    validity="DAY",
                    status="confirmed",
                    status_reason="待执行",
                    created_at=datetime.strptime(
                        "2026-03-25 15:05:00", "%Y-%m-%d %H:%M:%S"
                    ),
                )
                market_repo.upsert_eod_price(
                    symbol="000001",
                    symbol_name="平安银行",
                    trade_date="2026-03-25",
                    close_price=12.0,
                    open_price=11.4,
                    previous_close=11.0,
                    high_price=12.1,
                    low_price=11.3,
                    is_final=True,
                    source="test",
                    published_at=datetime.strptime(
                        "2026-03-25 15:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                )

            response = client.get(
                "/api/positions/000001/detail", headers={"x-user-id": user_id}
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["tradeDate"] == "2026-03-25"
        assert payload["sellableTradeDate"] == "2026-03-26"
        assert payload["marketStatus"] == "closed"
        assert payload["position"] == {
            "symbol": "000001",
            "name": "平安银行",
            "shares": 800,
            "sellableShares": 200,
            "frozenSellShares": 600,
            "costPrice": 10.075,
            "lastPrice": 12.0,
            "marketValue": 9600.0,
            "pnl": 1540.0,
            "returnRate": 1540.0 / 8060.0,
            "todayPnl": 800.0,
            "todayReturn": 1.0 / 11.0,
        }
        assert payload["lots"] == [
            {
                "id": payload["lots"][0]["id"],
                "openedDate": "2026-03-20",
                "openedAt": "2026-03-20 10:00:00",
                "originalShares": 500,
                "remainingShares": 500,
                "sellableShares": 500,
                "frozenSellShares": 500,
                "availableSellableShares": 0,
                "costPrice": 10.0,
                "costAmount": 5000.0,
                "marketValue": 6000.0,
            },
            {
                "id": payload["lots"][1]["id"],
                "openedDate": "2026-03-25",
                "openedAt": "2026-03-25 10:00:00",
                "originalShares": 300,
                "remainingShares": 300,
                "sellableShares": 300,
                "frozenSellShares": 100,
                "availableSellableShares": 200,
                "costPrice": 10.2,
                "costAmount": 3060.0,
                "marketValue": 3600.0,
            },
        ]
        assert payload["pendingSellOrders"] == [
            {
                "id": payload["pendingSellOrders"][0]["id"],
                "tradeDate": "2026-03-26",
                "orderPrice": 11.8,
                "lots": 6,
                "shares": 600,
                "validity": "DAY",
                "status": "confirmed",
                "statusMessage": "待执行",
                "createdAt": "2026-03-25 15:05:00",
                "updatedAt": "2026-03-25 15:05:00",
            }
        ]
    finally:
        settings.market_now_override = previous_override
