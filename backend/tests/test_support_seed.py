from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.config import settings
from app.db import session_scope
from app.models import DailyPnl, DailyPnlDetail, EodPrice, ExecutionTrade, PositionLot
from app.quote_client import DailyBar, TencentQuoteClient
from app.repositories import (
    MarketDataRepository,
    OrderRepository,
    PnlRepository,
    PortfolioRepository,
    UserRepository,
)
from devtools.sample_account import seed_sample_account
from devtools.rebuild_derived_data import rebuild_derived_data
from devtools.restore_test_user import restore_test_user
from tests.helpers import create_filled_buy_position


LEGACY_USER_NAME = "legacy-user"
REBUILD_USER_NAME = "rebuild-user"


def test_seed_sample_account_uses_expected_cash_and_pnl_baseline() -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T15:10:00+08:00"

    try:
        user_id = seed_sample_account()

        with session_scope() as session:
            cash_balance = PortfolioRepository(session).cash_balance(user_id)
            pnl = PnlRepository(session).get_daily_pnl(user_id, "2026-03-16")

        assert cash_balance == 362340.0
        assert pnl is not None
        assert pnl.total_assets == 521210.0
        assert pnl.daily_pnl == 21210.0
    finally:
        settings.market_now_override = previous_override


def test_seed_sample_account_refuses_nonempty_database() -> None:
    with session_scope() as session:
        UserRepository(session).create(name="existing-user", initial_cash=100000)

    try:
        seed_sample_account()
    except RuntimeError as exc:
        assert "仅可用于空库初始化" in str(exc)
    else:
        raise AssertionError("seed_sample_account should refuse non-empty databases")


def test_restore_test_user_replaces_existing_seed_account_and_removes_legacy_user(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        TencentQuoteClient,
        "fetch_quotes_sync",
        lambda self, symbols: [],
    )
    monkeypatch.setattr(
        TencentQuoteClient,
        "fetch_daily_bars_sync",
        lambda self, symbol, *, start_trade_date, end_trade_date: [],
    )

    with session_scope() as session:
        repo = UserRepository(session)
        repo.create(user_id="test-user", name="Test User", initial_cash=1)
        repo.create(name=LEGACY_USER_NAME, initial_cash=100000)

    summary = restore_test_user(delete_user_names=(LEGACY_USER_NAME,))

    removed_user_names = {row["name"] for row in summary["removedUsers"]}
    assert removed_user_names == {"Test User", LEGACY_USER_NAME}
    assert summary["restoredUser"]["id"] == "test-user"
    assert summary["counts"]["positions"] > 0
    assert summary["counts"]["history"] > 0
    assert summary["counts"]["calendar"] > 0

    with session_scope() as session:
        users = UserRepository(session).list_users()
        assert [user.id for user in users] == ["test-user"]
        assert users[0].name == "Test User"
        assert (session.scalar(select(func.count()).select_from(ExecutionTrade)) or 0) > 0
        assert (session.scalar(select(func.count()).select_from(PositionLot)) or 0) > 0


def test_restore_test_user_removes_all_duplicate_users_for_requested_names(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        TencentQuoteClient,
        "fetch_quotes_sync",
        lambda self, symbols: [],
    )
    monkeypatch.setattr(
        TencentQuoteClient,
        "fetch_daily_bars_sync",
        lambda self, symbol, *, start_trade_date, end_trade_date: [],
    )

    with session_scope() as session:
        repo = UserRepository(session)
        repo.create(name="api-user", initial_cash=100000)
        repo.create(name="api-user", initial_cash=100000)
        repo.create(name="api-user", initial_cash=100000)

    summary = restore_test_user(delete_user_names=("api-user",))

    removed_user_names = [row["name"] for row in summary["removedUsers"]]
    assert removed_user_names.count("api-user") == 3

    with session_scope() as session:
        users = UserRepository(session).list_users()
        assert [user.name for user in users] == ["Test User"]


def test_rebuild_derived_data_preserves_users_and_trade_facts(monkeypatch) -> None:
    previous_override = settings.market_now_override
    settings.market_now_override = "2026-03-25T15:10:00+08:00"

    def fake_fetch_daily_bars_sync(
        self,
        symbol: str,
        *,
        start_trade_date: str,
        end_trade_date: str,
    ) -> list[DailyBar]:
        assert symbol == "000001"
        assert start_trade_date == "2026-03-24"
        assert end_trade_date == "2026-03-25"
        return [
            DailyBar(
                symbol="000001",
                name="平安银行",
                trade_date="2026-03-24",
                open_price=10.0,
                close_price=10.0,
                high_price=10.1,
                low_price=9.9,
            ),
            DailyBar(
                symbol="000001",
                name="平安银行",
                trade_date="2026-03-25",
                open_price=10.3,
                close_price=10.5,
                high_price=10.6,
                low_price=10.2,
            ),
        ]

    monkeypatch.setattr(
        TencentQuoteClient,
        "fetch_daily_bars_sync",
        fake_fetch_daily_bars_sync,
    )

    try:
        with session_scope() as session:
            user_id = UserRepository(session).create(
                name=REBUILD_USER_NAME, initial_cash=100000
            ).id
            order_repo = OrderRepository(session)
            portfolio_repo = PortfolioRepository(session)
            market_repo = MarketDataRepository(session)
            pnl_repo = PnlRepository(session)

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
                fill_time=datetime.strptime("2026-03-24 10:00:00", "%Y-%m-%d %H:%M:%S"),
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
                close_price=99.0,
                open_price=98.0,
                previous_close=97.0,
                high_price=100.0,
                low_price=96.0,
                is_final=True,
                source="stale",
                published_at=datetime.strptime(
                    "2026-03-24 15:00:00", "%Y-%m-%d %H:%M:%S"
                ),
            )
            pnl_repo.upsert_daily_pnl(
                user_id=user_id,
                trade_date="2026-03-24",
                is_final=True,
                payload={
                    "totalAssets": 123456.0,
                    "availableCash": 99000.0,
                    "positionMarketValue": 24456.0,
                    "dailyPnl": 23456.0,
                    "dailyReturn": 0.23456,
                    "cumulativePnl": 23456.0,
                    "buyAmount": 1000.0,
                    "sellAmount": 0.0,
                    "tradeCount": 1,
                    "details": [
                        {
                            "symbol": "000001",
                            "symbolName": "平安银行",
                            "openingShares": 0,
                            "closingShares": 100,
                            "buyShares": 100,
                            "sellShares": 0,
                            "buyPrice": 10.0,
                            "sellPrice": 0.0,
                            "openPrice": 98.0,
                            "closePrice": 99.0,
                            "dailyPnl": 8900.0,
                            "dailyReturn": 8.9,
                            "marketValue": 9900.0,
                        }
                    ],
                },
            )

        summary = rebuild_derived_data()

        assert summary["users"] == [user_id]
        assert summary["symbols"] == ["000001"]
        assert summary["rebuiltTradeDates"] == 2
        assert summary["rebuiltEodRows"] == 2
        assert summary["historicalStartTradeDate"] == "2026-03-24"
        assert summary["historicalTargetTradeDate"] == "2026-03-25"

        with session_scope() as session:
            market_repo = MarketDataRepository(session)
            pnl_repo = PnlRepository(session)
            portfolio_repo = PortfolioRepository(session)

            assert UserRepository(session).list_user_ids() == [user_id]
            assert (
                session.scalar(select(func.count()).select_from(ExecutionTrade)) or 0
            ) == 1
            assert (
                session.scalar(select(func.count()).select_from(PositionLot)) or 0
            ) == 1
            assert portfolio_repo.cash_balance(user_id) == 99000.0

            rebuilt_eod = market_repo.get_eod_price("000001", "2026-03-24")
            assert rebuilt_eod is not None
            assert rebuilt_eod.close_price == 10.0
            assert rebuilt_eod.source == "tencent_raw_history"

            current_eod = market_repo.get_eod_price("000001", "2026-03-25")
            assert current_eod is not None
            assert current_eod.close_price == 10.5
            assert current_eod.is_final is True

            day_one = pnl_repo.get_daily_pnl(user_id, "2026-03-24")
            assert day_one is not None
            assert day_one.total_assets == 100000.0
            assert day_one.daily_pnl == 0.0
            assert day_one.cumulative_pnl == 0.0
            assert day_one.is_final is True

            day_two = pnl_repo.get_daily_pnl(user_id, "2026-03-25")
            assert day_two is not None
            assert day_two.total_assets == 100050.0
            assert day_two.daily_pnl == 50.0
            assert day_two.cumulative_pnl == 50.0
            assert day_two.is_final is True

            assert (
                session.scalar(select(func.count()).select_from(EodPrice)) or 0
            ) == 2
            assert (
                session.scalar(select(func.count()).select_from(DailyPnl)) or 0
            ) == 2
            assert (
                session.scalar(select(func.count()).select_from(DailyPnlDetail)) or 0
            ) == 2
    finally:
        settings.market_now_override = previous_override
