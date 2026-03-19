from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


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
