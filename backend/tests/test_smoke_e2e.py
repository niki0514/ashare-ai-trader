from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.import_io import parse_import_file
from app.main import app


SMOKE_TRADE_DATE = "2026-03-20"
SMOKE_MARKET_OVERRIDE = "2026-03-19T15:10:00+08:00"


def test_smoke_import_commit_and_key_readbacks() -> None:
    """Minimal repeatable smoke chain for API-level E2E acceptance."""
    previous_override = settings.market_now_override
    settings.market_now_override = SMOKE_MARKET_OVERRIDE
    try:
        with TestClient(app) as client:
            reset = client.post("/api/dev/reset-demo")
            assert reset.status_code == 200

            # 1) 下载导入模板
            template_resp = client.get("/api/imports/template", params={"targetTradeDate": SMOKE_TRADE_DATE})
            assert template_resp.status_code == 200
            assert (
                template_resp.headers.get("content-type")
                == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            template_content = template_resp.content
            parsed_template = parse_import_file("import-template.xlsx", template_content)
            assert parsed_template.source_type == "XLSX"
            assert len(parsed_template.rows) == 2

            # 2) 上传模板并预览
            preview_resp = client.post(
                "/api/imports/upload",
                data={"targetTradeDate": SMOKE_TRADE_DATE, "mode": "APPEND"},
                files={
                    "file": (
                        f"import-template-{SMOKE_TRADE_DATE}.xlsx",
                        template_content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
            assert preview_resp.status_code == 200
            preview = preview_resp.json()
            assert preview["batchId"]
            assert len(preview["rows"]) == 2
            assert any(row["validationStatus"] == "VALID" for row in preview["rows"])

            # 3) commit 导入
            commit_resp = client.post(
                "/api/imports/commit",
                json={"batchId": preview["batchId"], "mode": "APPEND"},
            )
            assert commit_resp.status_code == 200
            committed = commit_resp.json()
            assert committed["importedCount"] >= 1

            # 4) 挂单回读
            pending_resp = client.get("/api/orders/pending")
            assert pending_resp.status_code == 200
            pending_rows = pending_resp.json()["rows"]
            assert any(row["symbol"] == "600519" and row["side"] == "BUY" for row in pending_rows)

            # 5) 关键接口回读
            dashboard_resp = client.get("/api/dashboard")
            assert dashboard_resp.status_code == 200
            dashboard = dashboard_resp.json()
            assert dashboard["tradeDate"] == "2026-03-19"
            assert dashboard["metrics"]["totalAssets"] > 0

            positions_resp = client.get("/api/positions")
            assert positions_resp.status_code == 200
            positions_rows = positions_resp.json()["rows"]
            assert len(positions_rows) > 0

            history_resp = client.get("/api/history")
            assert history_resp.status_code == 200
            history_rows = history_resp.json()["rows"]
            assert len(history_rows) >= 11

            pnl_calendar_resp = client.get("/api/pnl/calendar")
            assert pnl_calendar_resp.status_code == 200
            pnl_calendar_rows = pnl_calendar_resp.json()["rows"]
            assert len(pnl_calendar_rows) >= 3

            pnl_daily_resp = client.get("/api/pnl/daily/2026-03-18")
            assert pnl_daily_resp.status_code == 200
            pnl_daily_rows = pnl_daily_resp.json()["rows"]
            assert len(pnl_daily_rows) > 0

            calendar_map = {row["date"]: row for row in pnl_calendar_rows}
            detail_sum = round(sum(row["dailyPnl"] for row in pnl_daily_rows), 6)
            assert round(calendar_map["2026-03-18"]["dailyPnl"], 6) == detail_sum
    finally:
        settings.market_now_override = previous_override
