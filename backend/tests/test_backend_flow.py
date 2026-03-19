from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.config import settings
from app.db import session_scope
from app.main import app
from app.quote_client import to_quote_symbol
from app.repositories import MarketDataRepository


def test_seed_history_and_positions() -> None:
    with TestClient(app) as client:
        reset = client.post("/api/dev/reset-demo")
        assert reset.status_code == 200

        history = client.get("/api/history").json()["rows"]
        assert len(history) == 11
        assert history[0]["symbol"] == "000547"
        assert history[0]["side"] == "SELL"
        assert history[0]["time"] == "2026-03-18 14:30:00"

        positions = client.get("/api/positions").json()["rows"]
        by_symbol = {row["symbol"]: row for row in positions}
        assert by_symbol["000021"]["shares"] == 1000
        assert by_symbol["000547"]["shares"] == 4000

        detail = client.get("/api/pnl/daily/2026-03-18").json()["rows"]
        detail_by_symbol = {row["symbol"]: row for row in detail}
        # 今日卖出后持仓会下降，但收益仍计入当日
        assert detail_by_symbol["000021"]["openingShares"] == 4000
        assert detail_by_symbol["000021"]["sellShares"] == 4000
        assert detail_by_symbol["000021"]["dailyPnl"] != 0


def test_user_isolation_default_test_data() -> None:
    with TestClient(app) as client:
        client.post("/api/dev/reset-demo")

        test_dashboard = client.get("/api/dashboard", headers={"x-user-id": "test"}).json()
        alice_dashboard = client.get("/api/dashboard", headers={"x-user-id": "alice"}).json()

        assert test_dashboard["metrics"]["totalAssets"] != alice_dashboard["metrics"]["totalAssets"]
        assert alice_dashboard["metrics"]["totalAssets"] == 500000.0

        alice_history = client.get("/api/history", headers={"x-user-id": "alice"}).json()["rows"]
        assert alice_history == []


def test_lunch_break_positions_and_dashboard_keep_morning_quotes() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-19T12:05:00+08:00"
    try:
        with TestClient(app) as client:
            reset = client.post("/api/dev/reset-demo")
            assert reset.status_code == 200

        with session_scope() as session:
            repo = MarketDataRepository(session)
            repo.upsert_quote_snapshot(
                {
                    "symbol": to_quote_symbol("000547"),
                    "name": "航天发展",
                    "price": 31.72,
                    "open": 31.55,
                    "previousClose": 31.40,
                    "high": 31.88,
                    "low": 31.20,
                    "updated_at": datetime(2026, 3, 19, 11, 29, 0),
                    "source": "test",
                }
            )
            repo.upsert_quote_snapshot(
                {
                    "symbol": to_quote_symbol("000021"),
                    "name": "深科技",
                    "price": 33.85,
                    "open": 33.01,
                    "previousClose": 33.63,
                    "high": 34.02,
                    "low": 32.88,
                    "updated_at": datetime(2026, 3, 19, 11, 29, 0),
                    "source": "test",
                }
            )
            session.commit()

        with TestClient(app) as client:
            dashboard = client.get("/api/dashboard").json()
            positions = client.get("/api/positions").json()["rows"]

        assert dashboard["marketStatus"] == "lunch_break"
        assert round(dashboard["metrics"]["dailyPnl"], 6) == 1500.0

        by_symbol = {row["symbol"]: row for row in positions}
        assert by_symbol["000547"]["lastPrice"] == 31.72
        assert round(by_symbol["000547"]["todayPnl"], 6) == 1280.0
        assert round(by_symbol["000547"]["todayReturn"], 6) == round((31.72 - 31.40) / 31.40, 6)
        assert by_symbol["000021"]["lastPrice"] == 33.85
        assert round(by_symbol["000021"]["todayPnl"], 6) == 220.0
        assert round(by_symbol["000021"]["todayReturn"], 6) == round((33.85 - 33.63) / 33.63, 6)
    finally:
        settings.market_now_override = previous_override
