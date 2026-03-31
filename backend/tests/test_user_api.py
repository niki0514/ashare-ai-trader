from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier, Lock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import session_scope
from app.import_io import parse_import_file
from app.main import app
from app.market import market_clock, next_trading_date, previous_trading_date
from app.market_prices import trade_date_of
from app.quote_client import DailyBar, Quote, TencentQuoteClient
from app.repositories import MarketDataRepository, OrderRepository, PnlRepository, PortfolioRepository, UserRepository
from app.services import PnlService, QueryService, TradingService
from app.time_utils import account_bootstrap_time
from app.user_service import UserService
from tests.helpers import create_filled_buy_position, create_filled_sell_execution


TEST_USER_NAME = "api-user"


def test_dashboard_requires_existing_user() -> None:

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 404
    assert response.json() == {"detail": "No user available"}


def test_create_user_and_query_empty_account() -> None:

    with TestClient(app) as client:
        create_response = client.post(
            "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
        )

        assert create_response.status_code == 200
        created_user = create_response.json()
        user_id = created_user["id"]

        users_response = client.get("/api/users")
        assert users_response.status_code == 200
        users = users_response.json()["rows"]
        assert len(users) == 1
        assert users[0]["id"] == user_id
        assert users[0]["name"] == TEST_USER_NAME
        assert users[0]["initialCash"] == 100000.0

        headers = {"x-user-id": user_id}

        dashboard_response = client.get("/api/dashboard", headers=headers)
        assert dashboard_response.status_code == 200
        dashboard = dashboard_response.json()
        assert dashboard["metrics"]["availableCash"] == 100000.0
        assert dashboard["metrics"]["positionMarketValue"] == 0.0
        assert dashboard["metrics"]["totalAssets"] == 100000.0
        assert dashboard["metrics"]["dailyPnl"] == 0.0
        assert dashboard["metrics"]["cumulativePnl"] == 0.0

        assert client.get("/api/positions", headers=headers).json() == {"rows": []}
        assert client.get("/api/history", headers=headers).json() == {"rows": []}
        assert client.get("/api/pnl/calendar", headers=headers).json() == {"rows": []}


def test_duplicate_user_name_is_rejected() -> None:

    with TestClient(app) as client:
        first = client.post(
            "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
        )
        second = client.post(
            "/api/users", json={"name": TEST_USER_NAME, "initialCash": 200000}
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"detail": "User name already exists"}


def test_clear_import_drafts_removes_saved_drafts_for_trade_date() -> None:

    with TestClient(app) as client:
        create_response = client.post(
            "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        headers = {"x-user-id": user_id}
        payload = {
            "targetTradeDate": "2026-03-25",
            "mode": "DRAFT",
            "sourceType": "MANUAL",
            "rows": [
                {
                    "symbol": "000001",
                    "side": "BUY",
                    "price": 10.5,
                    "lots": 1,
                    "validity": "DAY",
                }
            ],
        }

        first_preview = client.post("/api/imports/preview", json=payload, headers=headers)
        second_preview = client.post("/api/imports/preview", json=payload, headers=headers)
        assert first_preview.status_code == 200
        assert second_preview.status_code == 200

        latest_response = client.get("/api/imports/latest?tradeDate=2026-03-25", headers=headers)
        assert latest_response.status_code == 200
        assert len(latest_response.json()["rows"]) == 2

        clear_response = client.delete("/api/imports/draft?tradeDate=2026-03-25", headers=headers)
        assert clear_response.status_code == 200
        assert clear_response.json() == {"deletedCount": 2}

        latest_after_clear = client.get("/api/imports/latest?tradeDate=2026-03-25", headers=headers)
        assert latest_after_clear.status_code == 200
        assert latest_after_clear.json() == {"rows": []}


def test_upload_import_uses_current_template_fields_only() -> None:

    with TestClient(app) as client:
        create_response = client.post(
            "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        headers = {"x-user-id": user_id}

        csv_content = "\n".join(
            [
                "挂单时间,股票代码,方向,委托价,手数,挂单方式",
                "2026-03-25,000001,BUY,10.5,1,DAY",
                "2026-03-26,000002,SELL,11.2,2,GTC",
            ]
        ).encode("utf-8")

        response = client.post(
            "/api/imports/upload",
            headers=headers,
            data={"mode": "DRAFT"},
            files={"file": ("orders.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 200
        payload = response.json()
        rows = payload["rows"]
        assert set(payload["batchIds"]) == {"2026-03-25", "2026-03-26"}
        assert [row["tradeDate"] for row in rows] == ["2026-03-25", "2026-03-26"]
        assert [row["validity"] for row in rows] == ["DAY", "GTC"]


def test_resolve_symbols_persists_name_for_later_preview_without_refetch(monkeypatch) -> None:
    quoted_at = datetime.strptime("2026-03-25 11:30:00", "%Y-%m-%d %H:%M:%S")
    fetch_calls = 0

    def fake_fetch_quotes_sync(self, symbols: list[str]) -> list[Quote]:
        nonlocal fetch_calls
        fetch_calls += 1
        assert symbols == ["sz000001"]
        return [
            Quote(
                symbol="sz000001",
                name="平安银行",
                price=10.5,
                previous_close=10.0,
                open_price=10.2,
                high_price=10.8,
                low_price=9.9,
                updated_at=quoted_at,
            )
        ]

    monkeypatch.setattr(TencentQuoteClient, "fetch_quotes_sync", fake_fetch_quotes_sync)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        headers = {"x-user-id": user_id}

        resolve_response = client.post(
            "/api/symbols/resolve",
            json={"targetTradeDate": "2026-03-25", "symbols": ["000001"]},
            headers=headers,
        )
        assert resolve_response.status_code == 200
        assert resolve_response.json()["rows"] == [
            {
                "symbol": "000001",
                "name": "平安银行",
                "resolved": True,
                "referenceClose": 10.0,
                "source": "quote",
            }
        ]

        payload = {
            "targetTradeDate": "2026-03-25",
            "mode": "DRAFT",
            "sourceType": "MANUAL",
            "rows": [
                {
                    "symbol": "000001",
                    "side": "BUY",
                    "price": 10.5,
                    "lots": 1,
                    "validity": "DAY",
                }
            ],
        }

        preview_response = client.post("/api/imports/preview", json=payload, headers=headers)
        assert preview_response.status_code == 200
        assert preview_response.json()["rows"][0]["name"] == "平安银行"
        assert fetch_calls == 1

        latest_response = client.get("/api/imports/latest?tradeDate=2026-03-25", headers=headers)
        assert latest_response.status_code == 200
        latest_rows = latest_response.json()["rows"]
        assert len(latest_rows) == 1
        assert latest_rows[0]["items"][0]["name"] == "平安银行"
        assert fetch_calls == 1


def test_preview_import_fetches_missing_reference_close_for_price_limit_validation(
    monkeypatch,
) -> None:
    previous_override = settings.market_now_override
    quoted_at = datetime.strptime("2026-03-25 12:03:00", "%Y-%m-%d %H:%M:%S")
    fetch_calls = 0

    def fake_fetch_quotes_sync(self, symbols: list[str]) -> list[Quote]:
        nonlocal fetch_calls
        fetch_calls += 1
        assert symbols == ["sz000001"]
        return [
            Quote(
                symbol="sz000001",
                name="平安银行",
                price=10.5,
                previous_close=10.0,
                open_price=10.2,
                high_price=10.8,
                low_price=9.9,
                updated_at=quoted_at,
            )
        ]

    try:
        settings.market_now_override = "2026-03-25T12:05:00+08:00"
        monkeypatch.setattr(TencentQuoteClient, "fetch_quotes_sync", fake_fetch_quotes_sync)

        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            preview_payload = {
                "targetTradeDate": "2026-03-25",
                "mode": "DRAFT",
                "sourceType": "MANUAL",
                "rows": [
                    {
                        "symbol": "000001",
                        "side": "BUY",
                        "price": 11.5,
                        "lots": 1,
                        "validity": "DAY",
                    }
                ],
            }
            preview_response = client.post(
                "/api/imports/preview", json=preview_payload, headers=headers
            )

            assert preview_response.status_code == 200
            row = preview_response.json()["rows"][0]
            assert row["name"] == "平安银行"
            assert row["validationStatus"] == "ERROR"
            assert (
                row["validationMessage"]
                == "按昨收 10.00 计算，涨跌停区间为 9.00 - 11.00，当前委托价 11.50 超出范围"
            )
            assert fetch_calls == 1

        with session_scope() as session:
            quote = MarketDataRepository(session).latest_intraday_quote("sz000001")
            assert quote is not None
            assert quote.previous_close == 10.0
            assert quote.source == "tencent_preview_validation"
    finally:
        settings.market_now_override = previous_override


def test_preview_import_uses_previous_trading_day_close_for_future_trade_date(
    monkeypatch,
) -> None:
    previous_override = settings.market_now_override

    def fake_fetch_daily_bars_sync(
        self,
        symbol: str,
        *,
        start_trade_date: str,
        end_trade_date: str,
    ) -> list[DailyBar]:
        assert symbol == "002460"
        assert start_trade_date == "2026-03-27"
        assert end_trade_date == "2026-03-27"
        return [
            DailyBar(
                symbol="002460",
                name="赣锋锂业",
                trade_date="2026-03-27",
                open_price=71.49,
                close_price=79.67,
                high_price=79.67,
                low_price=71.49,
            )
        ]

    try:
        settings.market_now_override = "2026-03-27T15:10:00+08:00"
        monkeypatch.setattr(
            TencentQuoteClient, "fetch_daily_bars_sync", fake_fetch_daily_bars_sync
        )

        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            resolve_response = client.post(
                "/api/symbols/resolve",
                json={"targetTradeDate": "2026-03-30", "symbols": ["002460"]},
                headers=headers,
            )
            assert resolve_response.status_code == 200
            assert resolve_response.json()["rows"] == [
                {
                    "symbol": "002460",
                    "name": "赣锋锂业",
                    "resolved": True,
                    "referenceClose": 79.67,
                    "source": "eod",
                }
            ]

            preview_payload = {
                "targetTradeDate": "2026-03-30",
                "mode": "DRAFT",
                "sourceType": "MANUAL",
                "rows": [
                    {
                        "symbol": "002460",
                        "side": "BUY",
                        "price": 80.0,
                        "lots": 1,
                        "validity": "DAY",
                    }
                ],
            }
            preview_response = client.post(
                "/api/imports/preview", json=preview_payload, headers=headers
            )

            assert preview_response.status_code == 200
            row = preview_response.json()["rows"][0]
            assert row["name"] == "赣锋锂业"
            assert row["validationStatus"] == "VALID"
            assert row["validationMessage"] == "校验通过"

        with session_scope() as session:
            eod = MarketDataRepository(session).get_eod_price("002460", "2026-03-27")
            assert eod is not None
            assert eod.close_price == 79.67
            assert eod.source == "tencent_preview_validation"
    finally:
        settings.market_now_override = previous_override


def test_preview_import_marks_batch_sell_conflict_as_error() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T12:05:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            with session_scope() as session:
                portfolio_repo = PortfolioRepository(session)
                market_repo = MarketDataRepository(session)
                portfolio_repo.add_cash_entry(
                    user_id=user_id,
                    entry_time=datetime.strptime("2026-03-25 09:00:00", "%Y-%m-%d %H:%M:%S"),
                    entry_type="INITIAL",
                    amount=100000,
                    reference_type="Bootstrap",
                )
                create_filled_buy_position(
                    order_repo=OrderRepository(session),
                    portfolio_repo=portfolio_repo,
                    user_id=user_id,
                    trade_date="2026-03-24",
                    fill_time=datetime.strptime(
                        "2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.0,
                    lots=10,
                )
                market_repo.append_intraday_quote(
                    {
                        "symbol": "sz000001",
                        "name": "平安银行",
                        "trade_date": "2026-03-25",
                        "price": 10.5,
                        "open": 10.2,
                        "previousClose": 10.0,
                        "high": 10.8,
                        "low": 9.9,
                        "quoted_at": datetime.strptime(
                            "2026-03-25 12:03:00", "%Y-%m-%d %H:%M:%S"
                        ),
                        "source": "test",
                    }
                )

            preview_response = client.post(
                "/api/imports/preview",
                json={
                    "targetTradeDate": "2026-03-25",
                    "mode": "APPEND",
                    "sourceType": "MANUAL",
                    "rows": [
                        {
                            "symbol": "000001",
                            "side": "SELL",
                            "price": 10.5,
                            "lots": 6,
                            "validity": "DAY",
                        },
                        {
                            "symbol": "000001",
                            "side": "SELL",
                            "price": 10.5,
                            "lots": 5,
                            "validity": "DAY",
                        },
                    ],
                },
                headers=headers,
            )

            assert preview_response.status_code == 200
            rows = preview_response.json()["rows"]
            assert rows[0]["validationStatus"] == "VALID"
            assert rows[1]["validationStatus"] == "ERROR"
            assert "本批卖单累计将超出剩余可卖" in rows[1]["validationMessage"]
    finally:
        settings.market_now_override = previous_override


def test_preview_import_marks_batch_buy_conflict_as_error() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T12:05:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 10000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            with session_scope() as session:
                portfolio_repo = PortfolioRepository(session)
                market_repo = MarketDataRepository(session)
                market_repo.append_intraday_quote(
                    {
                        "symbol": "sz000001",
                        "name": "平安银行",
                        "trade_date": "2026-03-25",
                        "price": 10.0,
                        "open": 10.0,
                        "previousClose": 10.0,
                        "high": 10.1,
                        "low": 9.9,
                        "quoted_at": datetime.strptime(
                            "2026-03-25 12:03:00", "%Y-%m-%d %H:%M:%S"
                        ),
                        "source": "test",
                    }
                )

            preview_response = client.post(
                "/api/imports/preview",
                json={
                    "targetTradeDate": "2026-03-25",
                    "mode": "APPEND",
                    "sourceType": "MANUAL",
                    "rows": [
                        {
                            "symbol": "000001",
                            "side": "BUY",
                            "price": 10.0,
                            "lots": 6,
                            "validity": "DAY",
                        },
                        {
                            "symbol": "000001",
                            "side": "BUY",
                            "price": 10.0,
                            "lots": 5,
                            "validity": "DAY",
                        },
                    ],
                },
                headers=headers,
            )

            assert preview_response.status_code == 200
            rows = preview_response.json()["rows"]
            assert rows[0]["validationStatus"] == "VALID"
            assert rows[1]["validationStatus"] == "ERROR"
            assert "将超出可用现金" in rows[1]["validationMessage"]
    finally:
        settings.market_now_override = previous_override


def test_commit_imports_requires_warning_confirmation(monkeypatch) -> None:
    previous_override = settings.market_now_override

    try:
        settings.market_now_override = "2026-03-25T12:05:00+08:00"
        monkeypatch.setattr(
            TencentQuoteClient, "fetch_quotes_sync", lambda self, symbols: []
        )
        monkeypatch.setattr(
            TencentQuoteClient,
            "fetch_daily_bars_sync",
            lambda self, symbol, *, start_trade_date, end_trade_date: [],
        )
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            preview_response = client.post(
                "/api/imports/preview",
                json={
                    "targetTradeDate": "2026-03-25",
                    "mode": "APPEND",
                    "sourceType": "MANUAL",
                    "rows": [
                        {
                            "symbol": "000001",
                            "side": "BUY",
                            "price": 10.0,
                            "lots": 1,
                            "validity": "DAY",
                        }
                    ],
                },
                headers=headers,
            )

            assert preview_response.status_code == 200
            preview_body = preview_response.json()
            assert preview_body["rows"][0]["validationStatus"] == "WARNING"
            assert preview_body["confirmation"]["required"] is True
            assert preview_body["confirmation"]["items"] == [
                {
                    "code": "MISSING_REFERENCE_CLOSE",
                    "summary": "暂未获取到昨收盘口径，未校验涨跌停区间",
                    "rowNumbers": [1],
                }
            ]

            missing_confirmation_commit = client.post(
                "/api/imports/commit",
                json={"batchId": preview_body["batchId"], "mode": "APPEND"},
                headers=headers,
            )
            assert missing_confirmation_commit.status_code == 409
            assert (
                missing_confirmation_commit.json()["detail"]
                == "存在需确认的警告，请重新校验并确认后再提交"
            )

            confirmed_commit = client.post(
                "/api/imports/commit",
                json={
                    "batchId": preview_body["batchId"],
                    "mode": "APPEND",
                    "confirmWarnings": True,
                    "confirmationToken": preview_body["confirmation"]["token"],
                },
                headers=headers,
            )
            assert confirmed_commit.status_code == 200
            assert confirmed_commit.json()["importedCount"] == 1
    finally:
        settings.market_now_override = previous_override


def test_parse_import_file_uses_validation_message_for_successful_rows() -> None:
    csv_content = "\n".join(
        [
            "挂单时间,股票代码,方向,委托价,手数,挂单方式",
            "2026-03-25,000001,BUY,10.5,1,DAY",
        ]
    ).encode("utf-8")

    parsed = parse_import_file("orders.csv", csv_content)

    assert parsed.source_type == "CSV"
    assert parsed.rows == [
        {
            "rowNumber": 1,
            "tradeDate": "2026-03-25",
            "symbol": "000001",
            "side": "BUY",
            "price": 10.5,
            "lots": 1,
            "validity": "DAY",
            "validationStatus": "VALID",
            "validationMessage": "校验通过",
        }
    ]


def test_upload_import_rejects_legacy_alias_fields() -> None:

    with TestClient(app) as client:
        create_response = client.post(
            "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        headers = {"x-user-id": user_id}

        csv_content = "\n".join(
            [
                "tradedate,symbol,side,price,lots,validity",
                "2026-03-25,000001,BUY,10.5,1,DAY",
            ]
        ).encode("utf-8")

        response = client.post(
            "/api/imports/upload",
            headers=headers,
            data={"mode": "DRAFT"},
            files={"file": ("orders.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 400
        assert "导入模板缺少必填列" in response.json()["detail"]


def test_delete_pending_order_marks_order_as_cancelled() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T10:00:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                order = OrderRepository(session).create_order(
                    user_id=user_id,
                    trade_date="2026-03-25",
                    symbol="000547",
                    symbol_name=None,
                    side="BUY",
                    limit_price=12.34,
                    lots=2,
                    validity="DAY",
                )

            headers = {"x-user-id": user_id}
            pending_before = client.get("/api/orders/pending", headers=headers)
            assert pending_before.status_code == 200
            assert len(pending_before.json()["rows"]) == 1

            delete_response = client.delete(f"/api/orders/{order.id}", headers=headers)
            assert delete_response.status_code == 200
            assert delete_response.json() == {"deletedId": order.id}

            pending_after = client.get("/api/orders/pending", headers=headers)
            assert pending_after.status_code == 200
            rows = pending_after.json()["rows"]
            assert len(rows) == 1
            assert rows[0]["id"] == order.id
            assert rows[0]["status"] == "cancelled"
            assert rows[0]["statusMessage"] == "用户撤单"
            assert rows[0]["canDelete"] is False
    finally:
        settings.market_now_override = previous_override


def test_current_day_day_order_is_expired_after_close_on_query() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                OrderRepository(session).create_order(
                    user_id=user_id,
                    trade_date="2026-03-25",
                    symbol="000547",
                    symbol_name=None,
                    side="BUY",
                    limit_price=12.34,
                    lots=2,
                    validity="DAY",
                )

            response = client.get("/api/orders/pending", headers={"x-user-id": user_id})
            assert response.status_code == 200
            rows = response.json()["rows"]
            assert len(rows) == 1
            assert rows[0]["status"] == "expired"
            assert rows[0]["statusMessage"] == "当日未触价已失效"
            assert rows[0]["canDelete"] is False
    finally:
        settings.market_now_override = previous_override


def test_positions_project_sellable_shares_by_trade_date() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-23T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                create_filled_buy_position(
                    order_repo=OrderRepository(session),
                    portfolio_repo=PortfolioRepository(session),
                    user_id=user_id,
                    trade_date="2026-03-18",
                    fill_time=datetime.strptime(
                        "2026-03-18 10:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.0,
                    lots=10,
                )

            response = client.get("/api/positions", headers={"x-user-id": user_id})
            assert response.status_code == 200
            rows = response.json()["rows"]
            assert len(rows) == 1
            assert rows[0]["shares"] == 1000
            assert rows[0]["sellableShares"] == 1000
    finally:
        settings.market_now_override = previous_override


def test_positions_after_close_project_sellable_shares_for_next_trade_date() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                create_filled_buy_position(
                    order_repo=OrderRepository(session),
                    portfolio_repo=PortfolioRepository(session),
                    user_id=user_id,
                    trade_date="2026-03-25",
                    fill_time=datetime.strptime(
                        "2026-03-25 10:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.0,
                    lots=10,
                )

            response = client.get("/api/positions", headers={"x-user-id": user_id})
            assert response.status_code == 200
            rows = response.json()["rows"]
            assert len(rows) == 1
            assert rows[0]["shares"] == 1000
            assert rows[0]["sellableShares"] == 1000
    finally:
        settings.market_now_override = previous_override


def test_positions_use_diluted_cost_basis_and_align_with_dashboard_cumulative_pnl() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                order_repo = OrderRepository(session)
                portfolio_repo = PortfolioRepository(session)
                market_repo = MarketDataRepository(session)

                buy_time = datetime.strptime(
                    "2026-03-20 10:00:00", "%Y-%m-%d %H:%M:%S"
                )
                sell_time = datetime.strptime(
                    "2026-03-24 14:00:00", "%Y-%m-%d %H:%M:%S"
                )

                create_filled_buy_position(
                    order_repo=order_repo,
                    portfolio_repo=portfolio_repo,
                    user_id=user_id,
                    trade_date="2026-03-20",
                    fill_time=buy_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.0,
                    lots=10,
                    sellable_shares=1000,
                )
                create_filled_sell_execution(
                    order_repo=order_repo,
                    portfolio_repo=portfolio_repo,
                    user_id=user_id,
                    trade_date="2026-03-24",
                    fill_time=sell_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=12.0,
                    lots=4,
                )

                market_repo.upsert_eod_price(
                    symbol="000001",
                    symbol_name="平安银行",
                    trade_date="2026-03-24",
                    close_price=10.5,
                    open_price=10.2,
                    previous_close=10.0,
                    high_price=10.6,
                    low_price=10.1,
                    is_final=True,
                    source="test",
                    published_at=datetime.strptime(
                        "2026-03-24 15:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                )
                market_repo.upsert_eod_price(
                    symbol="000001",
                    symbol_name="平安银行",
                    trade_date="2026-03-25",
                    close_price=11.0,
                    open_price=10.6,
                    previous_close=10.5,
                    high_price=11.1,
                    low_price=10.5,
                    is_final=True,
                    source="test",
                    published_at=datetime.strptime(
                        "2026-03-25 15:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                )

            headers = {"x-user-id": user_id}
            positions_response = client.get("/api/positions", headers=headers)
            dashboard_response = client.get("/api/dashboard", headers=headers)

            assert positions_response.status_code == 200
            assert dashboard_response.status_code == 200

            rows = positions_response.json()["rows"]
            assert len(rows) == 1
            row = rows[0]
            assert row["symbol"] == "000001"
            assert row["shares"] == 600
            assert row["sellableShares"] == 600
            assert row["costPrice"] == pytest.approx(8.666666666666666)
            assert row["marketValue"] == 6600.0
            assert row["todayPnl"] == pytest.approx(300.0)
            assert row["pnl"] == pytest.approx(1400.0)
            assert row["returnRate"] == pytest.approx(1400.0 / 5200.0)

            dashboard = dashboard_response.json()
            assert dashboard["metrics"]["availableCash"] == pytest.approx(94800.0)
            assert dashboard["metrics"]["totalAssets"] == pytest.approx(101400.0)
            assert dashboard["metrics"]["cumulativePnl"] == pytest.approx(1400.0)
            assert sum(position["pnl"] for position in rows) == pytest.approx(
                dashboard["metrics"]["cumulativePnl"]
            )
    finally:
        settings.market_now_override = previous_override


def test_reopened_position_resets_return_rate_to_new_cycle() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": f"{TEST_USER_NAME}-reopen", "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                order_repo = OrderRepository(session)
                portfolio_repo = PortfolioRepository(session)
                market_repo = MarketDataRepository(session)

                first_buy_time = datetime.strptime(
                    "2026-03-20 10:00:00", "%Y-%m-%d %H:%M:%S"
                )
                close_time = datetime.strptime(
                    "2026-03-24 14:00:00", "%Y-%m-%d %H:%M:%S"
                )
                second_buy_time = datetime.strptime(
                    "2026-03-25 10:00:00", "%Y-%m-%d %H:%M:%S"
                )

                create_filled_buy_position(
                    order_repo=order_repo,
                    portfolio_repo=portfolio_repo,
                    user_id=user_id,
                    trade_date="2026-03-20",
                    fill_time=first_buy_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.0,
                    lots=10,
                    sellable_shares=1000,
                )
                create_filled_sell_execution(
                    order_repo=order_repo,
                    portfolio_repo=portfolio_repo,
                    user_id=user_id,
                    trade_date="2026-03-24",
                    fill_time=close_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=12.0,
                    lots=10,
                )
                create_filled_buy_position(
                    order_repo=order_repo,
                    portfolio_repo=portfolio_repo,
                    user_id=user_id,
                    trade_date="2026-03-25",
                    fill_time=second_buy_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=20.0,
                    lots=2,
                )

                market_repo.upsert_eod_price(
                    symbol="000001",
                    symbol_name="平安银行",
                    trade_date="2026-03-24",
                    close_price=12.0,
                    open_price=11.5,
                    previous_close=10.5,
                    high_price=12.1,
                    low_price=11.4,
                    is_final=True,
                    source="test",
                    published_at=datetime.strptime(
                        "2026-03-24 15:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                )
                market_repo.upsert_eod_price(
                    symbol="000001",
                    symbol_name="平安银行",
                    trade_date="2026-03-25",
                    close_price=21.0,
                    open_price=20.2,
                    previous_close=12.0,
                    high_price=21.2,
                    low_price=20.0,
                    is_final=True,
                    source="test",
                    published_at=datetime.strptime(
                        "2026-03-25 15:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                )

            headers = {"x-user-id": user_id}
            positions_response = client.get("/api/positions", headers=headers)
            dashboard_response = client.get("/api/dashboard", headers=headers)

            assert positions_response.status_code == 200
            assert dashboard_response.status_code == 200

            rows = positions_response.json()["rows"]
            assert len(rows) == 1
            row = rows[0]
            assert row["symbol"] == "000001"
            assert row["shares"] == 200
            assert row["sellableShares"] == 200
            assert row["costPrice"] == pytest.approx(20.0)
            assert row["marketValue"] == pytest.approx(4200.0)
            assert row["pnl"] == pytest.approx(200.0)
            assert row["returnRate"] == pytest.approx(0.05)

            dashboard = dashboard_response.json()
            assert dashboard["metrics"]["cumulativePnl"] == pytest.approx(2200.0)
    finally:
        settings.market_now_override = previous_override


def test_tick_backfills_missing_previous_trade_day_from_next_day_previous_close() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-23T15:10:00+08:00"

    try:
        with session_scope() as session:
            user_id = UserRepository(session).create(
                name=TEST_USER_NAME, initial_cash=100000
            ).id
            order_repo = OrderRepository(session)
            portfolio_repo = PortfolioRepository(session)
            market_repo = MarketDataRepository(session)
            pnl_repo = PnlRepository(session)
            pnl_service = PnlService(session)

            initial_time = datetime.strptime("2026-03-18 09:00:00", "%Y-%m-%d %H:%M:%S")
            fill_time = datetime.strptime("2026-03-18 10:00:00", "%Y-%m-%d %H:%M:%S")
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
                trade_date="2026-03-18",
                fill_time=fill_time,
                symbol="000001",
                symbol_name="平安银行",
                price=10.0,
                lots=10,
                sellable_shares=0,
            )

            market_repo.upsert_eod_price(
                symbol="000001",
                symbol_name="平安银行",
                trade_date="2026-03-19",
                close_price=10.0,
                open_price=10.0,
                previous_close=10.0,
                high_price=10.0,
                low_price=10.0,
                is_final=True,
                source="test",
                published_at=datetime.strptime("2026-03-19 15:00:00", "%Y-%m-%d %H:%M:%S"),
            )
            pnl_service.recompute_daily_pnl(user_id, "2026-03-19", use_realtime=False, is_final=True)

            market_repo.append_intraday_quote(
                {
                    "symbol": "sz000001",
                    "name": "平安银行",
                    "trade_date": "2026-03-23",
                    "price": 12.0,
                    "open": 12.0,
                    "previousClose": 11.0,
                    "high": 12.0,
                    "low": 12.0,
                    "quoted_at": datetime.strptime("2026-03-23 15:00:00", "%Y-%m-%d %H:%M:%S"),
                    "source": "test",
                }
            )
            market_repo.upsert_eod_price(
                symbol="000001",
                symbol_name="平安银行",
                trade_date="2026-03-23",
                close_price=12.0,
                open_price=12.0,
                previous_close=11.0,
                high_price=12.0,
                low_price=12.0,
                is_final=True,
                source="test",
                published_at=datetime.strptime("2026-03-23 15:00:00", "%Y-%m-%d %H:%M:%S"),
            )
            pnl_service.recompute_daily_pnl(user_id, "2026-03-23", use_realtime=False, is_final=True)

            asyncio.run(
                TradingService(session).tick(
                    user_id,
                    session_info=market_clock.get_session(),
                    phase_changed=False,
                )
            )

            pnl_20 = pnl_repo.get_daily_pnl(user_id, "2026-03-20")
            pnl_23 = pnl_repo.get_daily_pnl(user_id, "2026-03-23")

            assert pnl_20 is not None
            assert pnl_20.is_final is True
            assert pnl_20.total_assets == 101000.0
            assert pnl_20.daily_pnl == 1000.0

            assert pnl_23 is not None
            assert pnl_23.is_final is True
            assert pnl_23.total_assets == 102000.0
            assert pnl_23.daily_pnl == 1000.0
    finally:
        settings.market_now_override = previous_override


def test_tick_backfills_first_missing_trade_day_without_prior_daily_pnl() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-23T10:00:00+08:00"

    try:
        with session_scope() as session:
            user_id = UserRepository(session).create(
                name=TEST_USER_NAME, initial_cash=100000
            ).id
            order_repo = OrderRepository(session)
            portfolio_repo = PortfolioRepository(session)
            market_repo = MarketDataRepository(session)
            pnl_repo = PnlRepository(session)

            initial_time = datetime.strptime("2026-03-20 09:00:00", "%Y-%m-%d %H:%M:%S")
            fill_time = datetime.strptime("2026-03-20 10:00:00", "%Y-%m-%d %H:%M:%S")
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
                trade_date="2026-03-20",
                fill_time=fill_time,
                symbol="000001",
                symbol_name="平安银行",
                price=10.0,
                lots=1,
                sellable_shares=0,
            )
            market_repo.append_intraday_quote(
                {
                    "symbol": "sz000001",
                    "name": "平安银行",
                    "trade_date": "2026-03-23",
                    "price": 10.8,
                    "open": 10.6,
                    "previousClose": 10.5,
                    "high": 10.9,
                    "low": 10.4,
                    "quoted_at": datetime.strptime("2026-03-23 09:35:00", "%Y-%m-%d %H:%M:%S"),
                    "source": "test",
                }
            )

            asyncio.run(
                TradingService(session).tick(
                    user_id,
                    session_info=market_clock.get_session(),
                    phase_changed=False,
                )
            )

            pnl_20 = pnl_repo.get_daily_pnl(user_id, "2026-03-20")
            assert pnl_20 is not None
            assert pnl_20.is_final is True
            assert pnl_20.total_assets == pytest.approx(100050.0)
            assert pnl_20.daily_pnl == pytest.approx(50.0)
    finally:
        settings.market_now_override = previous_override


def test_calendar_query_backfills_missing_previous_trade_day_on_weekend() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-28T10:00:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            with session_scope() as session:
                order_repo = OrderRepository(session)
                portfolio_repo = PortfolioRepository(session)
                market_repo = MarketDataRepository(session)
                pnl_repo = PnlRepository(session)

                fill_time = datetime.strptime("2026-03-27 10:00:00", "%Y-%m-%d %H:%M:%S")
                create_filled_buy_position(
                    order_repo=order_repo,
                    portfolio_repo=portfolio_repo,
                    user_id=user_id,
                    trade_date="2026-03-27",
                    fill_time=fill_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.0,
                    lots=1,
                    sellable_shares=0,
                )
                market_repo.append_intraday_quote(
                    {
                        "symbol": "sz000001",
                        "name": "平安银行",
                        "trade_date": "2026-03-27",
                        "price": 10.5,
                        "open": 10.2,
                        "previousClose": 10.0,
                        "high": 10.6,
                        "low": 10.1,
                        "quoted_at": datetime.strptime(
                            "2026-03-27 15:00:00", "%Y-%m-%d %H:%M:%S"
                        ),
                        "source": "test",
                    }
                )

                assert pnl_repo.get_daily_pnl(user_id, "2026-03-27") is None

            calendar_response = client.get("/api/pnl/calendar", headers=headers)
            assert calendar_response.status_code == 200
            rows = calendar_response.json()["rows"]
            assert len(rows) == 1
            assert rows[0]["date"] == "2026-03-27"
            assert rows[0]["dailyPnl"] == pytest.approx(50.0)
            assert rows[0]["dailyReturn"] == pytest.approx(0.0005)
            assert rows[0]["tradeCount"] == 1

            with session_scope() as session:
                row = PnlRepository(session).get_daily_pnl(user_id, "2026-03-27")
                assert row is not None
                assert row.is_final is True
                assert row.daily_pnl == pytest.approx(50.0)
    finally:
        settings.market_now_override = previous_override


def test_dashboard_returns_server_suggested_import_trade_date() -> None:
    previous_override = settings.market_now_override

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            settings.market_now_override = "2026-03-23T09:00:00+08:00"
            pre_open_dashboard = client.get("/api/dashboard", headers=headers)
            assert pre_open_dashboard.status_code == 200
            assert pre_open_dashboard.json()["tradeDate"] == "2026-03-23"
            assert pre_open_dashboard.json()["suggestedImportTradeDate"] == "2026-03-23"

            settings.market_now_override = "2026-03-23T10:15:00+08:00"
            trading_dashboard = client.get("/api/dashboard", headers=headers)
            assert trading_dashboard.status_code == 200
            assert trading_dashboard.json()["tradeDate"] == "2026-03-23"
            assert trading_dashboard.json()["suggestedImportTradeDate"] == "2026-03-23"

            settings.market_now_override = "2026-03-23T12:05:00+08:00"
            lunch_break_dashboard = client.get("/api/dashboard", headers=headers)
            assert lunch_break_dashboard.status_code == 200
            assert lunch_break_dashboard.json()["tradeDate"] == "2026-03-23"
            assert lunch_break_dashboard.json()["suggestedImportTradeDate"] == "2026-03-23"

            settings.market_now_override = "2026-03-23T15:10:00+08:00"
            closed_dashboard = client.get("/api/dashboard", headers=headers)
            assert closed_dashboard.status_code == 200
            assert closed_dashboard.json()["tradeDate"] == "2026-03-23"
            assert closed_dashboard.json()["suggestedImportTradeDate"] == "2026-03-24"
    finally:
        settings.market_now_override = previous_override


def test_closed_dashboard_query_finalizes_trade_date_without_engine_tick() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                order_repo = OrderRepository(session)
                portfolio_repo = PortfolioRepository(session)
                market_repo = MarketDataRepository(session)
                pnl_repo = PnlRepository(session)
                pnl_service = PnlService(session)

                buy_time = datetime.strptime(
                    "2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S"
                )
                create_filled_buy_position(
                    order_repo=order_repo,
                    portfolio_repo=portfolio_repo,
                    user_id=user_id,
                    trade_date="2026-03-24",
                    fill_time=buy_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.0,
                    lots=10,
                    sellable_shares=1000,
                )

                market_repo.upsert_eod_price(
                    symbol="000001",
                    symbol_name="平安银行",
                    trade_date="2026-03-24",
                    close_price=10.0,
                    open_price=10.0,
                    previous_close=10.0,
                    high_price=10.0,
                    low_price=10.0,
                    is_final=True,
                    source="test",
                    published_at=datetime.strptime(
                        "2026-03-24 15:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                )
                pnl_service.recompute_daily_pnl(
                    user_id, "2026-03-24", use_realtime=False, is_final=True
                )

                market_repo.append_intraday_quote(
                    {
                        "symbol": "sz000001",
                        "name": "平安银行",
                        "trade_date": "2026-03-25",
                        "price": 11.0,
                        "open": 10.6,
                        "previousClose": 10.0,
                        "high": 11.0,
                        "low": 10.5,
                        "quoted_at": datetime.strptime(
                            "2026-03-25 15:00:00", "%Y-%m-%d %H:%M:%S"
                        ),
                        "source": "test",
                    }
                )
                assert pnl_repo.get_daily_pnl(user_id, "2026-03-25") is None

            headers = {"x-user-id": user_id}
            dashboard = client.get("/api/dashboard", headers=headers)
            calendar = client.get("/api/pnl/calendar", headers=headers)

            assert dashboard.status_code == 200
            assert calendar.status_code == 200
            assert dashboard.json()["metrics"]["dailyPnl"] == pytest.approx(1000.0)
            assert calendar.json()["rows"][-1]["date"] == "2026-03-25"

            with session_scope() as session:
                row = PnlRepository(session).get_daily_pnl(user_id, "2026-03-25")
                assert row is not None
                assert row.is_final is True
                assert row.daily_pnl == pytest.approx(1000.0)
    finally:
        settings.market_now_override = previous_override


def test_daily_detail_excludes_symbols_after_they_are_fully_closed() -> None:
    with session_scope() as session:
        user_id = UserRepository(session).create(
            name=TEST_USER_NAME, initial_cash=100000
        ).id
        order_repo = OrderRepository(session)
        portfolio_repo = PortfolioRepository(session)
        market_repo = MarketDataRepository(session)
        pnl_repo = PnlRepository(session)
        pnl_service = PnlService(session)
        query_service = QueryService(session)

        initial_time = datetime.strptime("2026-03-24 09:00:00", "%Y-%m-%d %H:%M:%S")
        buy_time = datetime.strptime("2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S")
        sell_time = datetime.strptime("2026-03-25 10:05:00", "%Y-%m-%d %H:%M:%S")
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
            fill_time=buy_time,
            symbol="000001",
            symbol_name="平安银行",
            price=10.0,
            lots=1,
            sellable_shares=100,
        )

        market_repo.upsert_eod_price(
            symbol="000001",
            symbol_name="平安银行",
            trade_date="2026-03-24",
            close_price=10.0,
            open_price=10.0,
            previous_close=10.0,
            high_price=10.0,
            low_price=10.0,
            is_final=True,
            source="test",
            published_at=datetime.strptime("2026-03-24 15:00:00", "%Y-%m-%d %H:%M:%S"),
        )
        pnl_service.recompute_daily_pnl(
            user_id, "2026-03-24", use_realtime=False, is_final=True
        )

        create_filled_sell_execution(
            order_repo=order_repo,
            portfolio_repo=portfolio_repo,
            user_id=user_id,
            trade_date="2026-03-25",
            fill_time=sell_time,
            symbol="000001",
            symbol_name="平安银行",
            price=11.2,
            lots=1,
        )

        market_repo.upsert_eod_price(
            symbol="000001",
            symbol_name="平安银行",
            trade_date="2026-03-25",
            close_price=11.2,
            open_price=10.6,
            previous_close=10.0,
            high_price=11.2,
            low_price=10.5,
            is_final=True,
            source="test",
            published_at=datetime.strptime("2026-03-25 15:00:00", "%Y-%m-%d %H:%M:%S"),
        )
        pnl_service.recompute_daily_pnl(
            user_id, "2026-03-25", use_realtime=False, is_final=True
        )

        pnl_service.recompute_daily_pnl(
            user_id, "2026-03-26", use_realtime=False, is_final=True
        )

        day_after_close = pnl_repo.get_daily_pnl(user_id, "2026-03-26")
        assert day_after_close is not None
        assert day_after_close.daily_pnl == pytest.approx(0.0)
        assert query_service.get_daily_detail(user_id, "2026-03-26") == []
        assert pnl_repo.list_detail_rows(user_id, "2026-03-26") == []


def test_lunch_break_dashboard_persists_non_final_snapshot_but_calendar_stays_final_only() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T12:05:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                order_repo = OrderRepository(session)
                portfolio_repo = PortfolioRepository(session)
                market_repo = MarketDataRepository(session)
                pnl_repo = PnlRepository(session)
                pnl_service = PnlService(session)

                buy_time = datetime.strptime(
                    "2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S"
                )
                create_filled_buy_position(
                    order_repo=order_repo,
                    portfolio_repo=portfolio_repo,
                    user_id=user_id,
                    trade_date="2026-03-24",
                    fill_time=buy_time,
                    symbol="000001",
                    symbol_name="平安银行",
                    price=10.0,
                    lots=10,
                    sellable_shares=1000,
                )

                market_repo.upsert_eod_price(
                    symbol="000001",
                    symbol_name="平安银行",
                    trade_date="2026-03-24",
                    close_price=10.0,
                    open_price=10.0,
                    previous_close=10.0,
                    high_price=10.0,
                    low_price=10.0,
                    is_final=True,
                    source="test",
                    published_at=datetime.strptime(
                        "2026-03-24 15:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                )
                pnl_service.recompute_daily_pnl(
                    user_id, "2026-03-24", use_realtime=False, is_final=True
                )

                market_repo.append_intraday_quote(
                    {
                        "symbol": "sz000001",
                        "name": "平安银行",
                        "trade_date": "2026-03-25",
                        "price": 10.5,
                        "open": 10.3,
                        "previousClose": 10.0,
                        "high": 10.6,
                        "low": 10.2,
                        "quoted_at": datetime.strptime(
                            "2026-03-25 12:00:00", "%Y-%m-%d %H:%M:%S"
                        ),
                        "source": "test",
                    }
                )
                assert pnl_repo.get_daily_pnl(user_id, "2026-03-25") is None

            headers = {"x-user-id": user_id}
            dashboard = client.get("/api/dashboard", headers=headers)
            calendar = client.get("/api/pnl/calendar", headers=headers)

            assert dashboard.status_code == 200
            assert dashboard.json()["metrics"]["dailyPnl"] == pytest.approx(500.0)
            assert calendar.status_code == 200
            assert [row["date"] for row in calendar.json()["rows"]] == ["2026-03-24"]

            with session_scope() as session:
                row = PnlRepository(session).get_daily_pnl(user_id, "2026-03-25")
                assert row is not None
                assert row.is_final is False
                assert row.daily_pnl == pytest.approx(500.0)
    finally:
        settings.market_now_override = previous_override


def test_lunch_break_concurrent_dashboard_queries_share_one_snapshot_persist(
    monkeypatch,
) -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T12:05:00+08:00"

    try:
        with session_scope() as session:
            user_id = UserService(session).create_user(
                name=f"{TEST_USER_NAME}-concurrent",
                initial_cash=100000,
            ).id
            order_repo = OrderRepository(session)
            portfolio_repo = PortfolioRepository(session)
            market_repo = MarketDataRepository(session)
            pnl_repo = PnlRepository(session)
            pnl_service = PnlService(session)

            buy_time = datetime.strptime(
                "2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S"
            )
            create_filled_buy_position(
                order_repo=order_repo,
                portfolio_repo=portfolio_repo,
                user_id=user_id,
                trade_date="2026-03-24",
                fill_time=buy_time,
                symbol="000001",
                symbol_name="平安银行",
                price=10.0,
                lots=10,
                sellable_shares=1000,
            )

            market_repo.upsert_eod_price(
                symbol="000001",
                symbol_name="平安银行",
                trade_date="2026-03-24",
                close_price=10.0,
                open_price=10.0,
                previous_close=10.0,
                high_price=10.0,
                low_price=10.0,
                is_final=True,
                source="test",
                published_at=datetime.strptime(
                    "2026-03-24 15:00:00", "%Y-%m-%d %H:%M:%S"
                ),
            )
            pnl_service.recompute_daily_pnl(
                user_id, "2026-03-24", use_realtime=False, is_final=True
            )

            market_repo.append_intraday_quote(
                {
                    "symbol": "sz000001",
                    "name": "平安银行",
                    "trade_date": "2026-03-25",
                    "price": 10.5,
                    "open": 10.3,
                    "previousClose": 10.0,
                    "high": 10.6,
                    "low": 10.2,
                    "quoted_at": datetime.strptime(
                        "2026-03-25 12:00:00", "%Y-%m-%d %H:%M:%S"
                    ),
                    "source": "test",
                }
            )
            assert pnl_repo.get_daily_pnl(user_id, "2026-03-25") is None

        original_recompute_daily_pnl = PnlService.recompute_daily_pnl
        recompute_calls = 0
        recompute_calls_lock = Lock()

        def wrapped_recompute_daily_pnl(
            self,
            user_id: str,
            trade_date: str,
            use_realtime: bool,
            is_final: bool,
            persist: bool = True,
        ):
            nonlocal recompute_calls
            if trade_date == "2026-03-25" and persist and not is_final:
                with recompute_calls_lock:
                    recompute_calls += 1
                time.sleep(0.1)
            return original_recompute_daily_pnl(
                self,
                user_id,
                trade_date,
                use_realtime=use_realtime,
                is_final=is_final,
                persist=persist,
            )

        monkeypatch.setattr(
            PnlService,
            "recompute_daily_pnl",
            wrapped_recompute_daily_pnl,
        )

        start_barrier = Barrier(4)

        def worker() -> dict:
            start_barrier.wait()
            with session_scope() as session:
                return QueryService(session).get_dashboard(user_id)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = [
                future.result()
                for future in [executor.submit(worker) for _ in range(4)]
            ]

        assert recompute_calls == 1
        assert [
            result["metrics"]["dailyPnl"] for result in results
        ] == pytest.approx([500.0, 500.0, 500.0, 500.0])

        with session_scope() as session:
            row = PnlRepository(session).get_daily_pnl(user_id, "2026-03-25")
            assert row is not None
            assert row.is_final is False
            assert row.daily_pnl == pytest.approx(500.0)
    finally:
        settings.market_now_override = previous_override


def test_commit_imports_is_allowed_during_lunch_break() -> None:
    previous_override = settings.market_now_override

    try:
        settings.market_now_override = "2026-03-23T12:05:00+08:00"
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            preview_payload = {
                "targetTradeDate": "2026-03-23",
                "mode": "APPEND",
                "sourceType": "MANUAL",
                "rows": [
                    {
                        "symbol": "000001",
                        "side": "BUY",
                        "price": 10.5,
                        "lots": 1,
                        "validity": "DAY",
                    }
                ],
            }
            preview_response = client.post("/api/imports/preview", json=preview_payload, headers=headers)
            assert preview_response.status_code == 200
            preview_body = preview_response.json()
            batch_id = preview_body["batchId"]

            commit_response = client.post(
                "/api/imports/commit",
                json={
                    "batchId": batch_id,
                    "mode": "APPEND",
                    "confirmWarnings": preview_body["confirmation"]["required"],
                    "confirmationToken": preview_body["confirmation"]["token"],
                },
                headers=headers,
            )
            assert commit_response.status_code == 200
            assert commit_response.json()["targetTradeDate"] == "2026-03-23"
            assert commit_response.json()["importedCount"] == 1
    finally:
        settings.market_now_override = previous_override


def test_commit_imports_is_blocked_during_trading_session() -> None:
    previous_override = settings.market_now_override

    try:
        settings.market_now_override = "2026-03-23T10:15:00+08:00"
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            preview_payload = {
                "targetTradeDate": "2026-03-23",
                "mode": "DRAFT",
                "sourceType": "MANUAL",
                "rows": [
                    {
                        "symbol": "000001",
                        "side": "BUY",
                        "price": 10.5,
                        "lots": 1,
                        "validity": "DAY",
                    }
                ],
            }
            preview_response = client.post("/api/imports/preview", json=preview_payload, headers=headers)
            assert preview_response.status_code == 200
            batch_id = preview_response.json()["batchId"]

            commit_response = client.post(
                "/api/imports/commit",
                json={"batchId": batch_id, "mode": "APPEND"},
                headers=headers,
            )
            assert commit_response.status_code == 403
            assert commit_response.json() == {"detail": "当前为交易时段，仅允许在休盘时提交导入"}
    finally:
        settings.market_now_override = previous_override


def test_commit_imports_is_allowed_after_market_close(monkeypatch) -> None:
    previous_override = settings.market_now_override
    quoted_at = datetime.strptime("2026-03-25 15:05:00", "%Y-%m-%d %H:%M:%S")
    fetch_calls = 0

    def fake_fetch_quotes_sync(self, symbols: list[str]) -> list[Quote]:
        nonlocal fetch_calls
        fetch_calls += 1
        assert symbols == ["sz000001"]
        return [
            Quote(
                symbol="sz000001",
                name="平安银行",
                price=10.5,
                previous_close=10.0,
                open_price=10.2,
                high_price=10.8,
                low_price=9.9,
                updated_at=quoted_at,
            )
        ]

    try:
        settings.market_now_override = "2026-03-25T15:10:00+08:00"
        monkeypatch.setattr(TencentQuoteClient, "fetch_quotes_sync", fake_fetch_quotes_sync)
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}
            next_trade_date = next_trading_date("2026-03-25")

            resolve_response = client.post(
                "/api/symbols/resolve",
                json={"targetTradeDate": next_trade_date, "symbols": ["000001"]},
                headers=headers,
            )
            assert resolve_response.status_code == 200
            assert resolve_response.json()["rows"][0]["name"] == "平安银行"

            preview_payload = {
                "targetTradeDate": next_trade_date,
                "mode": "DRAFT",
                "sourceType": "MANUAL",
                "rows": [
                    {
                        "symbol": "000001",
                        "side": "BUY",
                        "price": 10.5,
                        "lots": 1,
                        "validity": "DAY",
                    }
                ],
            }
            preview_response = client.post("/api/imports/preview", json=preview_payload, headers=headers)
            assert preview_response.status_code == 200
            batch_id = preview_response.json()["batchId"]

            commit_response = client.post(
                "/api/imports/commit",
                json={"batchId": batch_id, "mode": "APPEND"},
                headers=headers,
            )
            assert commit_response.status_code == 200
            assert commit_response.json()["targetTradeDate"] == next_trade_date
            assert commit_response.json()["importedCount"] == 1

            pending_response = client.get("/api/orders/pending", headers=headers)
            assert pending_response.status_code == 200
            assert pending_response.json()["rows"][0]["name"] == "平安银行"
            assert fetch_calls == 1

            with session_scope() as session:
                order = OrderRepository(session).list_orders(user_id)[0]
                assert order.symbol_name == "平安银行"
    finally:
        settings.market_now_override = previous_override


def test_commit_imports_revalidates_with_remote_fetch_when_cached_quote_is_missing(
    monkeypatch,
) -> None:
    previous_override = settings.market_now_override
    quoted_at = datetime.strptime("2026-03-25 12:06:00", "%Y-%m-%d %H:%M:%S")
    fetch_calls = 0

    def fake_fetch_quotes_sync(self, symbols: list[str]) -> list[Quote]:
        nonlocal fetch_calls
        fetch_calls += 1
        assert symbols == ["sz000001"]
        return [
            Quote(
                symbol="sz000001",
                name="平安银行",
                price=10.5,
                previous_close=10.0,
                open_price=10.2,
                high_price=10.8,
                low_price=9.9,
                updated_at=quoted_at,
            )
        ]

    try:
        settings.market_now_override = "2026-03-25T12:05:00+08:00"
        monkeypatch.setattr(TencentQuoteClient, "fetch_quotes_sync", fake_fetch_quotes_sync)

        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            with session_scope() as session:
                MarketDataRepository(session).append_intraday_quote(
                    {
                        "symbol": "sz000001",
                        "name": "平安银行",
                        "trade_date": "2026-03-25",
                        "price": 10.5,
                        "open": 10.2,
                        "previousClose": 10.0,
                        "high": 10.8,
                        "low": 9.9,
                        "quoted_at": datetime.strptime(
                            "2026-03-25 11:59:00", "%Y-%m-%d %H:%M:%S"
                        ),
                        "source": "test",
                    }
                )

            preview_payload = {
                "targetTradeDate": "2026-03-25",
                "mode": "DRAFT",
                "sourceType": "MANUAL",
                "rows": [
                    {
                        "symbol": "000001",
                        "side": "BUY",
                        "price": 10.5,
                        "lots": 1,
                        "validity": "DAY",
                    }
                ],
            }
            preview_response = client.post(
                "/api/imports/preview", json=preview_payload, headers=headers
            )
            assert preview_response.status_code == 200
            assert preview_response.json()["rows"][0]["validationStatus"] == "VALID"
            assert fetch_calls == 0
            batch_id = preview_response.json()["batchId"]

            with session_scope() as session:
                market_repo = MarketDataRepository(session)
                market_repo.delete_intraday_quotes(symbols=["sz000001"])
                market_repo.delete_eod_prices(symbols=["000001"])

            commit_response = client.post(
                "/api/imports/commit",
                json={"batchId": batch_id, "mode": "APPEND"},
                headers=headers,
            )
            assert commit_response.status_code == 200
            assert fetch_calls == 1

            with session_scope() as session:
                batch = OrderRepository(session).get_import_batch(batch_id)
                assert batch is not None
                assert batch.items[0].validation_status.value == "VALID"
                assert batch.items[0].validation_message == "校验通过"

                quote = MarketDataRepository(session).latest_intraday_quote("sz000001")
                assert quote is not None
                assert quote.source == "tencent_preview_validation"
    finally:
        settings.market_now_override = previous_override


def test_pending_orders_without_symbol_name_falls_back_to_symbol_only() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T10:00:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                order_repo = OrderRepository(session)
                market_repo = MarketDataRepository(session)
                order_repo.create_order(
                    user_id=user_id,
                    trade_date="2026-03-25",
                    symbol="000001",
                    symbol_name=None,
                    side="BUY",
                    limit_price=10.5,
                    lots=1,
                    validity="DAY",
                )
                market_repo.append_intraday_quote(
                    {
                        "symbol": "sz000001",
                        "name": "平安银行",
                        "trade_date": "2026-03-25",
                        "price": 10.5,
                        "open": 10.2,
                        "previousClose": 10.0,
                        "high": 10.8,
                        "low": 9.9,
                        "quoted_at": datetime.strptime(
                            "2026-03-25 09:35:00", "%Y-%m-%d %H:%M:%S"
                        ),
                        "source": "test",
                    }
                )

            pending_response = client.get("/api/orders/pending", headers={"x-user-id": user_id})
            assert pending_response.status_code == 200
            assert pending_response.json()["rows"][0]["name"] == "000001"
    finally:
        settings.market_now_override = previous_override


def test_preview_import_rejects_same_day_order_after_market_close() -> None:
    previous_override = settings.market_now_override

    try:
        settings.market_now_override = "2026-03-25T15:10:00+08:00"
        with TestClient(app) as client:
            create_response = client.post(
                "/api/users", json={"name": TEST_USER_NAME, "initialCash": 100000}
            )
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]
            headers = {"x-user-id": user_id}

            preview_payload = {
                "targetTradeDate": "2026-03-25",
                "mode": "DRAFT",
                "sourceType": "MANUAL",
                "rows": [
                    {
                        "symbol": "000001",
                        "side": "BUY",
                        "price": 10.5,
                        "lots": 1,
                        "validity": "DAY",
                    }
                ],
            }
            preview_response = client.post("/api/imports/preview", json=preview_payload, headers=headers)

            assert preview_response.status_code == 200
            assert preview_response.json()["rows"][0]["validationStatus"] == "ERROR"
            assert (
                preview_response.json()["rows"][0]["validationMessage"]
                == "2026-03-25 已收盘，挂单时间必须晚于 2026-03-25"
            )
    finally:
        settings.market_now_override = previous_override


def test_future_gtc_order_is_not_activated_before_trade_date() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T10:00:00+08:00"

    try:
        with session_scope() as session:
            user_id = UserRepository(session).create(
                name=TEST_USER_NAME, initial_cash=100000
            ).id
            order_repo = OrderRepository(session)
            portfolio_repo = PortfolioRepository(session)
            market_repo = MarketDataRepository(session)

            portfolio_repo.add_cash_entry(
                user_id=user_id,
                entry_time=datetime.strptime("2026-03-25 09:00:00", "%Y-%m-%d %H:%M:%S"),
                entry_type="INITIAL",
                amount=100000,
                reference_type="Bootstrap",
            )
            future_order = order_repo.create_order(
                user_id=user_id,
                trade_date="2026-03-26",
                symbol="000001",
                symbol_name="平安银行",
                side="BUY",
                limit_price=10.0,
                lots=1,
                validity="GTC",
            )
            market_repo.append_intraday_quote(
                {
                    "symbol": "sz000001",
                    "name": "平安银行",
                    "trade_date": "2026-03-25",
                    "price": 9.8,
                    "open": 9.9,
                    "previousClose": 10.0,
                    "high": 10.0,
                    "low": 9.8,
                    "quoted_at": datetime.strptime("2026-03-25 10:00:00", "%Y-%m-%d %H:%M:%S"),
                    "source": "test",
                }
            )

            processed = asyncio.run(
                TradingService(session).tick(
                    user_id,
                    session_info=market_clock.get_session(),
                    phase_changed=False,
                )
            )

            orders = OrderRepository(session).list_orders(user_id)
            assert processed == 0
            assert len(orders) == 1
            assert orders[0].id == future_order.id
            assert orders[0].status.value == "confirmed"
            assert orders[0].trades == []
    finally:
        settings.market_now_override = previous_override


def test_future_day_sell_order_does_not_freeze_today_sellable_shares() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T10:00:00+08:00"

    try:
        with session_scope() as session:
            user_id = UserRepository(session).create(
                name=TEST_USER_NAME, initial_cash=100000
            ).id
            portfolio_repo = PortfolioRepository(session)
            order_repo = OrderRepository(session)

            portfolio_repo.add_cash_entry(
                user_id=user_id,
                entry_time=datetime.strptime("2026-03-24 09:00:00", "%Y-%m-%d %H:%M:%S"),
                entry_type="INITIAL",
                amount=100000,
                reference_type="Bootstrap",
            )
            create_filled_buy_position(
                order_repo=order_repo,
                portfolio_repo=portfolio_repo,
                user_id=user_id,
                trade_date="2026-03-24",
                fill_time=datetime.strptime(
                    "2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S"
                ),
                symbol="000001",
                symbol_name="平安银行",
                price=10.0,
                lots=10,
            )
            order_repo.create_order(
                user_id=user_id,
                trade_date="2026-03-26",
                symbol="000001",
                symbol_name="平安银行",
                side="SELL",
                limit_price=11.0,
                lots=5,
                validity="DAY",
            )

            rows = QueryService(session).get_positions(user_id)
            assert len(rows) == 1
            assert rows[0]["shares"] == 1000
            assert rows[0]["sellableShares"] == 1000
            assert rows[0]["frozenSellShares"] == 0
    finally:
        settings.market_now_override = previous_override


def test_overwrite_import_preserves_filled_history_and_replaces_active_orders() -> None:

    with session_scope() as session:
        user_id = UserRepository(session).create(
            name=TEST_USER_NAME, initial_cash=100000
        ).id
        order_repo = OrderRepository(session)
        portfolio_repo = PortfolioRepository(session)

        initial_time = datetime.strptime("2026-03-25 09:00:00", "%Y-%m-%d %H:%M:%S")
        fill_time = datetime.strptime("2026-03-25 10:00:00", "%Y-%m-%d %H:%M:%S")
        portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=initial_time,
            entry_type="INITIAL",
            amount=100000,
            reference_type="Bootstrap",
        )

        filled_order = order_repo.create_order(
            user_id=user_id,
            trade_date="2026-03-25",
            symbol="000001",
            symbol_name="平安银行",
            side="BUY",
            limit_price=10.0,
            lots=1,
            validity="DAY",
            status="filled",
            status_reason="成交完成",
            created_at=fill_time,
        )
        order_repo.create_trade(
            user_id=user_id,
            order_id=filled_order.id,
            symbol="000001",
            side="BUY",
            order_price=10.0,
            fill_price=10.0,
            cost_basis_amount=1000.0,
            realized_pnl=0.0,
            lots=1,
            shares=100,
            fill_time=fill_time,
            cash_after=99000.0,
            position_after=100,
        )

        active_order = order_repo.create_order(
            user_id=user_id,
            trade_date="2026-03-25",
            symbol="000002",
            symbol_name="万科A",
            side="BUY",
            limit_price=12.0,
            lots=2,
            validity="DAY",
        )

        batch = order_repo.create_import_batch(
            user_id=user_id,
            target_trade_date="2026-03-25",
            source_type="MANUAL",
            file_name=None,
            mode="OVERWRITE",
            rows=[
                {
                    "rowNumber": 1,
                    "symbol": "000858",
                    "side": "SELL",
                    "price": 130.0,
                    "lots": 3,
                    "validity": "DAY",
                    "validationStatus": "VALID",
                    "validationMessage": "校验通过",
                }
            ],
        )

        imported_count = order_repo.commit_import_batch(batch, "OVERWRITE")
        orders = order_repo.list_orders(user_id)

        assert imported_count == 1
        assert len(orders) == 2
        assert {order.status.value for order in orders} == {"filled", "confirmed"}
        assert filled_order.id in {order.id for order in orders}
        assert active_order.id not in {order.id for order in orders}
        assert sum(len(order.trades) for order in orders) == 1
        assert any(order.symbol == "000858" and order.status.value == "confirmed" for order in orders)


def test_market_clock_recognizes_official_holiday() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-05-01T10:00:00+08:00"

    try:
        session = market_clock.get_session()
        assert session.trade_date == "2026-05-01"
        assert session.market_status == "holiday"
        assert market_clock.is_import_window_open() is True
        assert market_clock.suggested_import_trade_date() == "2026-05-06"
        assert next_trading_date("2026-05-01") == "2026-05-06"
        assert previous_trading_date("2026-05-06") == "2026-04-30"
    finally:
        settings.market_now_override = previous_override


def test_tick_skips_holiday_trade_date_without_creating_pnl() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-05-01T10:00:00+08:00"

    try:
        with session_scope() as session:
            user_id = UserRepository(session).create(
                name=TEST_USER_NAME, initial_cash=100000
            ).id
            PortfolioRepository(session).add_cash_entry(
                user_id=user_id,
                entry_time=datetime.strptime("2026-04-30 09:00:00", "%Y-%m-%d %H:%M:%S"),
                entry_type="INITIAL",
                amount=100000,
                reference_type="Bootstrap",
            )

            processed = asyncio.run(
                TradingService(session).tick(
                    user_id,
                    session_info=market_clock.get_session(),
                    phase_changed=False,
                )
            )

            assert processed == 0
            assert PnlRepository(session).get_daily_pnl(user_id, "2026-05-01") is None
    finally:
        settings.market_now_override = previous_override


def test_user_creation_bootstraps_cash_before_any_backfilled_trade() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T10:00:00+08:00"

    try:
        with session_scope() as session:
            user = UserService(session).create_user(
                name=TEST_USER_NAME, initial_cash=100000
            )
            latest_cash = PortfolioRepository(session).latest_cash(user.id)

            assert user.created_at == datetime.strptime(
                "2026-03-25 10:00:00", "%Y-%m-%d %H:%M:%S"
            )
            assert latest_cash is not None
            assert latest_cash.entry_time == account_bootstrap_time()
    finally:
        settings.market_now_override = previous_override


def test_trade_date_of_normalizes_utc_timestamp_to_market_date() -> None:
    assert trade_date_of(datetime.fromisoformat("2026-03-24T16:30:00+00:00")) == "2026-03-25"
