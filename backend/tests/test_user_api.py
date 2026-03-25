from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, engine, init_schema
from app.db import session_scope
from app.main import app
from app.market import market_clock
from app.repositories import MarketDataRepository, OrderRepository, PnlRepository, PortfolioRepository, UserRepository
from app.services import PnlService, TradingService


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    init_schema()


def test_dashboard_requires_existing_user() -> None:
    reset_database()

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 404
    assert response.json() == {"detail": "No user available"}


def test_create_user_and_query_empty_account() -> None:
    reset_database()

    with TestClient(app) as client:
        create_response = client.post("/api/users", json={"name": "alice", "initialCash": 100000})

        assert create_response.status_code == 200
        created_user = create_response.json()
        user_id = created_user["id"]

        users_response = client.get("/api/users")
        assert users_response.status_code == 200
        users = users_response.json()["rows"]
        assert len(users) == 1
        assert users[0]["id"] == user_id
        assert users[0]["name"] == "alice"
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
    reset_database()

    with TestClient(app) as client:
        first = client.post("/api/users", json={"name": "alice", "initialCash": 100000})
        second = client.post("/api/users", json={"name": "alice", "initialCash": 200000})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"detail": "User name already exists"}


def test_clear_import_drafts_removes_saved_drafts_for_trade_date() -> None:
    reset_database()

    with TestClient(app) as client:
        create_response = client.post("/api/users", json={"name": "alice", "initialCash": 100000})
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
    reset_database()

    with TestClient(app) as client:
        create_response = client.post("/api/users", json={"name": "alice", "initialCash": 100000})
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


def test_upload_import_rejects_legacy_alias_fields() -> None:
    reset_database()

    with TestClient(app) as client:
        create_response = client.post("/api/users", json={"name": "alice", "initialCash": 100000})
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
    reset_database()
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T10:00:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post("/api/users", json={"name": "alice", "initialCash": 100000})
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
    reset_database()
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post("/api/users", json={"name": "alice", "initialCash": 100000})
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
    reset_database()
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-23T15:10:00+08:00"

    try:
        with TestClient(app) as client:
            create_response = client.post("/api/users", json={"name": "alice", "initialCash": 100000})
            assert create_response.status_code == 200
            user_id = create_response.json()["id"]

            with session_scope() as session:
                portfolio_repo = PortfolioRepository(session)
                portfolio_repo.create_position_lot(
                    user_id=user_id,
                    symbol="000001",
                    symbol_name="平安银行",
                    opened_order_id=None,
                    opened_trade_id=None,
                    opened_date="2026-03-18",
                    opened_at=datetime.strptime("2026-03-18 10:00:00", "%Y-%m-%d %H:%M:%S"),
                    cost_price=10.0,
                    original_shares=1000,
                    remaining_shares=1000,
                    sellable_shares=0,
                )

            response = client.get("/api/positions", headers={"x-user-id": user_id})
            assert response.status_code == 200
            rows = response.json()["rows"]
            assert len(rows) == 1
            assert rows[0]["shares"] == 1000
            assert rows[0]["sellableShares"] == 1000
    finally:
        settings.market_now_override = previous_override


def test_tick_backfills_missing_previous_trade_day_from_next_day_previous_close() -> None:
    reset_database()
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-23T15:10:00+08:00"

    try:
        with session_scope() as session:
            user_id = UserRepository(session).create(name="alice", initial_cash=100000).id
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
                balance_after=100000,
                reference_type="Bootstrap",
            )
            order = order_repo.create_order(
                user_id=user_id,
                trade_date="2026-03-18",
                symbol="000001",
                symbol_name="平安银行",
                side="BUY",
                limit_price=10.0,
                lots=10,
                validity="DAY",
                status="filled",
                status_reason="成交完成",
                created_at=fill_time,
            )
            order_repo.create_trade(
                user_id=user_id,
                order_id=order.id,
                symbol="000001",
                side="BUY",
                order_price=10.0,
                fill_price=10.0,
                cost_basis_amount=10000.0,
                realized_pnl=0.0,
                lots=10,
                shares=1000,
                fill_time=fill_time,
                cash_after=90000.0,
                position_after=1000,
            )
            portfolio_repo.add_cash_entry(
                user_id=user_id,
                entry_time=fill_time,
                entry_type="BUY",
                amount=-10000.0,
                balance_after=90000.0,
                reference_type="ExecutionTrade",
            )
            portfolio_repo.create_position_lot(
                user_id=user_id,
                symbol="000001",
                symbol_name="平安银行",
                opened_order_id=order.id,
                opened_trade_id=None,
                opened_date="2026-03-18",
                opened_at=fill_time,
                cost_price=10.0,
                original_shares=1000,
                remaining_shares=1000,
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


def test_dashboard_returns_server_suggested_import_trade_date() -> None:
    reset_database()
    previous_override = settings.market_now_override

    try:
        with TestClient(app) as client:
            create_response = client.post("/api/users", json={"name": "alice", "initialCash": 100000})
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


def test_commit_imports_is_allowed_during_lunch_break() -> None:
    reset_database()
    previous_override = settings.market_now_override

    try:
        settings.market_now_override = "2026-03-23T12:05:00+08:00"
        with TestClient(app) as client:
            create_response = client.post("/api/users", json={"name": "alice", "initialCash": 100000})
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
            assert commit_response.status_code == 200
            assert commit_response.json()["targetTradeDate"] == "2026-03-23"
            assert commit_response.json()["importedCount"] == 1
    finally:
        settings.market_now_override = previous_override
