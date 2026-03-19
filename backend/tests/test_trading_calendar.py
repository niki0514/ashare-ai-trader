from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.config import settings
from app.db import session_scope
from app.main import app
from app.quote_client import to_quote_symbol
from app.repositories import MarketDataRepository, PnlRepository
from app.services import PnlService


def test_calendar_reads_only_persisted_rows() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-19T10:00:00+08:00"

    try:
        with TestClient(app) as client:
            reset = client.post("/api/dev/reset-demo")
            assert reset.status_code == 200

            rows = client.get("/api/pnl/calendar").json()["rows"]
            assert [row["date"] for row in rows] == ["2026-03-16", "2026-03-17", "2026-03-18"]
    finally:
        settings.market_now_override = previous_override


def test_calendar_hides_current_day_until_finalized() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-19T10:00:00+08:00"

    try:
        with TestClient(app) as client:
            reset = client.post("/api/dev/reset-demo")
            assert reset.status_code == 200

        with session_scope() as session:
            pnl_service = PnlService(session)
            pnl_service.recompute_daily_pnl(settings.default_user_id, "2026-03-19", use_realtime=False, is_final=False)
            session.commit()

        with TestClient(app) as client:
            rows = {row["date"]: row for row in client.get("/api/pnl/calendar").json()["rows"]}
            assert "2026-03-19" not in rows

        with session_scope() as session:
            pnl_service = PnlService(session)
            pnl_service.recompute_daily_pnl(settings.default_user_id, "2026-03-19", use_realtime=False, is_final=True)
            session.commit()

        with TestClient(app) as client:
            rows = {row["date"]: row for row in client.get("/api/pnl/calendar").json()["rows"]}
            assert "2026-03-19" in rows
            assert rows["2026-03-19"]["dailyPnl"] is not None
    finally:
        settings.market_now_override = previous_override


def test_closed_market_keeps_current_day_non_final_when_only_stale_quotes_exist() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-19T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            reset = client.post("/api/dev/reset-demo")
            assert reset.status_code == 200

            dashboard = client.get("/api/dashboard").json()
            assert dashboard["tradeDate"] == "2026-03-19"
            assert dashboard["metrics"]["dailyPnl"] == 0.0

        with session_scope() as session:
            pnl_row = PnlRepository(session).get_daily_pnl(settings.default_user_id, "2026-03-19")
            assert pnl_row is not None
            assert pnl_row.is_final is False
            assert MarketDataRepository(session).list_daily_prices("2026-03-19") == []
    finally:
        settings.market_now_override = previous_override


def test_closed_market_finalizes_when_same_day_quotes_are_present() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-19T15:10:00+08:00"

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
                    "updated_at": datetime(2026, 3, 19, 14, 59, 0),
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
                    "updated_at": datetime(2026, 3, 19, 14, 59, 0),
                    "source": "test",
                }
            )
            session.commit()

        with TestClient(app) as client:
            dashboard = client.get("/api/dashboard").json()
            assert round(dashboard["metrics"]["dailyPnl"], 6) == 1500.0

            rows = {row["date"]: row for row in client.get("/api/pnl/calendar").json()["rows"]}
            assert "2026-03-19" in rows
            assert round(rows["2026-03-19"]["dailyPnl"], 6) == 1500.0

        with session_scope() as session:
            pnl_row = PnlRepository(session).get_daily_pnl(settings.default_user_id, "2026-03-19")
            assert pnl_row is not None
            assert pnl_row.is_final is True

            prices = {row.symbol: row for row in MarketDataRepository(session).list_daily_prices("2026-03-19")}
            assert prices["000021"].source == "close_settlement"
            assert prices["000547"].source == "close_settlement"
    finally:
        settings.market_now_override = previous_override
