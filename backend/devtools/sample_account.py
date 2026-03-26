from __future__ import annotations

from app.db import session_scope
from app.market import market_clock
from app.repositories import (
    MarketDataRepository,
    OrderRepository,
    PortfolioRepository,
    UserRepository,
)
from app.services import PnlService
from devtools.schema import reset_db
from devtools.safety import require_postgres_confirmation
from devtools.test_user_seed import (
    TEST_INITIAL_CASH,
    TEST_USER_ID,
    TEST_USER_NAME,
    sample_trade_dates_before,
    seed_market_data,
    seed_trades,
)


def reset_database() -> None:
    reset_db()


def seed_sample_account(
    *,
    user_id: str = TEST_USER_ID,
    name: str = TEST_USER_NAME,
    initial_cash: float = TEST_INITIAL_CASH,
) -> str:
    require_postgres_confirmation(
        action="uv run python -m devtools.sample_account",
        confirm_env="ASHARE_CONFIRM_SAMPLE_ACCOUNT_RESET",
        expected_value="RESET_SAMPLE_ACCOUNT",
    )
    reset_database()
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
        f"Seeded sample account {TEST_USER_NAME} ({TEST_USER_ID}) after resetting the database."
    )


if __name__ == "__main__":
    main()
