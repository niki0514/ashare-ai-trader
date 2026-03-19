from __future__ import annotations

from fastapi.testclient import TestClient

from app.import_io import build_import_template, parse_import_file
from app.main import app
from app.config import settings


def test_generated_template_can_round_trip_parse() -> None:
    content = build_import_template("2026-03-20")
    parsed = parse_import_file("import-template.xlsx", content)

    assert parsed.source_type == "XLSX"
    assert len(parsed.rows) == 2
    assert parsed.rows[0]["symbol"] == "600519"
    assert parsed.rows[0]["validationStatus"] == "VALID"
    assert parsed.rows[1]["symbol"] == "000858"
    assert parsed.rows[1]["validationStatus"] == "VALID"


def test_upload_and_commit_import_template_flow() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-19T15:10:00+08:00"
    try:
        template = build_import_template("2026-03-20")
        with TestClient(app) as client:
            reset = client.post("/api/dev/reset-demo")
            assert reset.status_code == 200

            upload = client.post(
                "/api/imports/upload",
                data={"targetTradeDate": "2026-03-20", "mode": "APPEND"},
                files={
                    "file": (
                        "import-template-2026-03-20.xlsx",
                        template,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
            assert upload.status_code == 200
            preview = upload.json()
            assert len(preview["rows"]) == 2
            assert preview["rows"][0]["symbol"] == "600519"
            assert preview["rows"][0]["validationStatus"] == "VALID"
            assert preview["rows"][1]["symbol"] == "000858"
            assert preview["rows"][1]["validationStatus"] == "ERROR"
            assert "当前无可卖仓位" in preview["rows"][1]["validationMessage"]

            commit = client.post(
                "/api/imports/commit",
                json={"batchId": preview["batchId"], "mode": "APPEND"},
            )
            assert commit.status_code == 200
            committed = commit.json()
            assert committed["importedCount"] == 1

            pending = client.get("/api/orders/pending")
            assert pending.status_code == 200
            rows = pending.json()["rows"]
            assert any(row["symbol"] == "600519" and row["side"] == "BUY" for row in rows)
    finally:
        settings.market_now_override = previous_override


def test_preview_can_save_draft_outside_import_window_but_commit_is_blocked() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-19T10:00:00+08:00"
    try:
        with TestClient(app) as client:
            reset = client.post("/api/dev/reset-demo")
            assert reset.status_code == 200

            preview = client.post(
                "/api/imports/preview",
                json={
                    "targetTradeDate": "2026-03-20",
                    "mode": "DRAFT",
                    "sourceType": "MANUAL",
                    "rows": [
                        {
                            "symbol": "600519",
                            "side": "BUY",
                            "price": 1688.0,
                            "lots": 1,
                            "validity": "DAY",
                        }
                    ],
                },
            )
            assert preview.status_code == 200
            preview_payload = preview.json()
            assert preview_payload["batchId"]
            assert preview_payload["rows"][0]["validationStatus"] == "VALID"

            commit = client.post(
                "/api/imports/commit",
                json={"batchId": preview_payload["batchId"], "mode": "APPEND"},
            )
            assert commit.status_code == 403
            assert commit.json()["detail"] == "仅允许在交易所收盘后或开盘前提交导入"
    finally:
        settings.market_now_override = previous_override
