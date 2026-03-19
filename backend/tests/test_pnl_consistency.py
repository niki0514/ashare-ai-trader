from __future__ import annotations

from collections import defaultdict

from fastapi.testclient import TestClient

from app.db import session_scope
from app.main import app
from app.repositories import PnlRepository
from app.config import settings


EXPECTED_PNL_ROWS = {
    "2026-03-16": {"totalAssets": 521210.0, "dailyPnl": 21210.0, "cumulativePnl": 21210.0},
    "2026-03-17": {"totalAssets": 508980.0, "dailyPnl": -12230.0, "cumulativePnl": 8980.0},
    "2026-03-18": {"totalAssets": 521570.0, "dailyPnl": 12590.0, "cumulativePnl": 21570.0},
}


def test_asset_delta_source_of_truth_calendar_rows() -> None:
    with TestClient(app) as client:
        reset = client.post("/api/dev/reset-demo")
        assert reset.status_code == 200

    with session_scope() as session:
        repo = PnlRepository(session)
        rows = repo.list_calendar_rows(settings.default_user_id)
        assert [row.trade_date for row in rows] == ["2026-03-16", "2026-03-17", "2026-03-18"]
        for row in rows:
            expected = EXPECTED_PNL_ROWS[row.trade_date]
            assert row.total_assets == expected["totalAssets"]
            assert row.daily_pnl == expected["dailyPnl"]
            assert row.cumulative_pnl == expected["cumulativePnl"]


def test_asset_delta_source_of_truth_detail_sum_matches_calendar() -> None:
    with TestClient(app) as client:
        reset = client.post("/api/dev/reset-demo")
        assert reset.status_code == 200

        calendar_rows = {row["date"]: row for row in client.get("/api/pnl/calendar").json()["rows"]}
        for trade_date, expected in EXPECTED_PNL_ROWS.items():
            detail_rows = client.get(f"/api/pnl/daily/{trade_date}").json()["rows"]
            detail_sum = round(sum(row["dailyPnl"] for row in detail_rows), 6)
            calendar_value = round(calendar_rows[trade_date]["dailyPnl"], 6)
            assert calendar_value == expected["dailyPnl"]
            assert detail_sum == expected["dailyPnl"]


def test_detail_daily_pnl_matches_unified_formula() -> None:
    with TestClient(app) as client:
        reset = client.post("/api/dev/reset-demo")
        assert reset.status_code == 200

        history_rows = client.get("/api/history").json()["rows"]
        trade_amounts: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"BUY": 0.0, "SELL": 0.0})
        for row in history_rows:
            trade_date = row["fillTime"][:10]
            key = (trade_date, row["symbol"])
            trade_amounts[key][row["side"]] += row["fillPrice"] * row["shares"]

        prev_close_by_symbol: dict[str, float] = {}
        for trade_date in EXPECTED_PNL_ROWS:
            detail_rows = client.get(f"/api/pnl/daily/{trade_date}").json()["rows"]
            next_prev_close_by_symbol: dict[str, float] = {}
            for row in detail_rows:
                symbol = row["symbol"]
                opening_shares = row["openingShares"]
                closing_shares = row["closingShares"]
                buy_shares = row["buyShares"]
                sell_shares = row["sellShares"]

                # 仓位字段保持自洽
                assert opening_shares + buy_shares - sell_shares == closing_shares

                buy_amount = trade_amounts[(trade_date, symbol)]["BUY"]
                sell_amount = trade_amounts[(trade_date, symbol)]["SELL"]
                if opening_shares > 0:
                    assert symbol in prev_close_by_symbol
                prev_close = prev_close_by_symbol.get(symbol, row["closePrice"])

                formula_daily_pnl = (
                    row["closePrice"] * closing_shares
                    + sell_amount
                    - prev_close * opening_shares
                    - buy_amount
                )
                assert round(formula_daily_pnl, 6) == round(row["dailyPnl"], 6)
                next_prev_close_by_symbol[symbol] = row["closePrice"]

            prev_close_by_symbol = next_prev_close_by_symbol
