from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.db import session_scope
from app.main import app
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
