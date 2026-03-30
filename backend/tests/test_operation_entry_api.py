from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.db import session_scope
from app.main import app
from app.repositories import OrderRepository


def test_operation_entry_validate_and_submit_flow_creates_orders() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-23T12:05:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": "operation-entry-user", "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            validate_response = client.post(
                "/api/operations/validate",
                json={
                    "targetTradeDate": "2026-03-24",
                    "mode": "APPEND",
                    "rows": [
                        {
                            "symbol": "000001",
                            "side": "BUY",
                            "price": 10.5,
                            "lots": 1,
                            "validity": "DAY",
                        }
                    ],
                },
                headers=headers,
            )

            assert validate_response.status_code == 200
            validated = validate_response.json()
            assert validated["targetTradeDate"] == "2026-03-24"
            assert validated["sourceType"] == "MANUAL"
            assert len(validated["rows"]) == 1
            assert validated["rows"][0]["tradeDate"] == "2026-03-24"
            assert validated["rows"][0]["symbol"] == "000001"
            assert validated["rows"][0]["side"] == "BUY"
            assert validated["rows"][0]["price"] == 10.5
            assert validated["rows"][0]["lots"] == 1
            assert validated["rows"][0]["validity"] == "DAY"

            submit_response = client.post(
                "/api/operations/submit",
                json={
                    "batchId": validated["batchId"],
                    "mode": "APPEND",
                    "confirmWarnings": validated["confirmation"]["required"],
                    "confirmationToken": validated["confirmation"]["token"],
                },
                headers=headers,
            )

            assert submit_response.status_code == 200
            assert submit_response.json() == {
                "batchId": validated["batchId"],
                "targetTradeDate": "2026-03-24",
                "mode": "APPEND",
                "importedCount": 1,
            }

            with session_scope() as session:
                orders = OrderRepository(session).list_orders(user_id)

            assert len(orders) == 1
            order = orders[0]
            assert order.trade_date == "2026-03-24"
            assert order.symbol == "000001"
            assert order.side.value == "BUY"
            assert order.limit_price == 10.5
            assert order.lots == 1
            assert order.validity.value == "DAY"
            assert order.status.value == "confirmed"
    finally:
        settings.market_now_override = previous_override
