from __future__ import annotations

from sqlalchemy import func, select

from app.db import session_scope
from app.market import market_clock
from app.models import CashLedger, ExecutionTrade, ImportBatch, InstructionOrder, PositionLot, User
from app.repositories import (
    MarketDataRepository,
    OrderRepository,
    PortfolioRepository,
    UserRepository,
)
from app.services import PnlService
from devtools.schema import init_db
from devtools.safety import require_postgres_confirmation
from devtools.test_user_seed import (
    TEST_INITIAL_CASH,
    TEST_USER_ID,
    TEST_USER_NAME,
    sample_trade_dates_before,
    seed_market_data,
    seed_trades,
)


def _assert_sample_account_target_is_empty() -> None:
    with session_scope() as session:
        row_counts = {
            "users": session.scalar(select(func.count()).select_from(User)) or 0,
            "orders": session.scalar(select(func.count()).select_from(InstructionOrder)) or 0,
            "trades": session.scalar(select(func.count()).select_from(ExecutionTrade)) or 0,
            "cash": session.scalar(select(func.count()).select_from(CashLedger)) or 0,
            "positions": session.scalar(select(func.count()).select_from(PositionLot)) or 0,
            "imports": session.scalar(select(func.count()).select_from(ImportBatch)) or 0,
        }

    if any(row_counts.values()):
        raise RuntimeError(
            "当前数据库已包含业务数据，sample_account 仅可用于空库初始化，不会覆盖现有数据。"
        )


def seed_sample_account(
    *,
    user_id: str = TEST_USER_ID,
    name: str = TEST_USER_NAME,
    initial_cash: float = TEST_INITIAL_CASH,
) -> str:
    require_postgres_confirmation(
        action="uv run python -m devtools.sample_account",
        confirm_env="ASHARE_CONFIRM_SAMPLE_ACCOUNT_INIT",
        expected_value="INIT_SAMPLE_ACCOUNT",
    )
    init_db()
    _assert_sample_account_target_is_empty()
    as_of_trade_date = market_clock.get_session().trade_date
    trade_dates = sample_trade_dates_before(as_of_trade_date)

    with session_scope() as session:
        user_repo = UserRepository(session)
        order_repo = OrderRepository(session)
        portfolio_repo = PortfolioRepository(session)
        market_repo = MarketDataRepository(session)
        pnl_service = PnlService(session)

        user_repo.create(user_id=user_id, name=name, initial_cash=initial_cash)
        seed_trades(
            order_repo=order_repo,
            portfolio_repo=portfolio_repo,
            user_id=user_id,
            initial_cash=initial_cash,
            as_of_trade_date=as_of_trade_date,
        )
        seed_market_data(market_repo=market_repo, trade_dates=trade_dates)

        for trade_date in trade_dates:
            pnl_service.recompute_daily_pnl(
                user_id, trade_date, use_realtime=False, is_final=True
            )

    return user_id


def main() -> None:
    seed_sample_account()
    print(
        f"Seeded sample account {TEST_USER_NAME} ({TEST_USER_ID}) into an empty database."
    )


if __name__ == "__main__":
    main()
