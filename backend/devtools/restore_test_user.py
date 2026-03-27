from __future__ import annotations

import json
from collections.abc import Iterable

from app.db import session_scope
from app.market import market_clock, next_trading_date, previous_trading_date
from app.quote_client import TencentQuoteClient, to_quote_symbol
from app.repositories import (
    MarketDataRepository,
    OrderRepository,
    PortfolioRepository,
    UserRepository,
)
from app.services import PnlService, QueryService
from app.time_utils import combine_market_datetime
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

def _calendar_target_trade_date() -> str:
    session = market_clock.get_session()
    if session.market_status in {"weekend", "holiday"}:
        return previous_trading_date(session.trade_date)
    return session.trade_date


def _tracked_symbols(
    *, portfolio_repo: PortfolioRepository, user_id: str
) -> list[str]:
    return sorted({lot.symbol for lot in portfolio_repo.open_lots(user_id)})


def _sync_latest_quotes(
    *,
    market_repo: MarketDataRepository,
    symbols: list[str],
) -> list[str]:
    if not symbols:
        return []

    synced_trade_dates: set[str] = set()
    for quote in TencentQuoteClient().fetch_quotes_sync(
        [to_quote_symbol(symbol) for symbol in symbols]
    ):
        trade_date = quote.updated_at.strftime("%Y-%m-%d")
        market_repo.append_intraday_quote(
            {
                "symbol": quote.symbol,
                "name": quote.name,
                "trade_date": trade_date,
                "price": quote.price,
                "open": quote.open_price,
                "previousClose": quote.previous_close,
                "high": quote.high_price,
                "low": quote.low_price,
                "quoted_at": quote.updated_at,
                "source": "tencent",
            }
        )
        synced_trade_dates.add(trade_date)
    return sorted(synced_trade_dates)


def _sync_historical_eod_prices(
    *,
    market_repo: MarketDataRepository,
    symbols: list[str],
    seed_trade_dates: list[str],
) -> list[str]:
    if not seed_trade_dates:
        return []

    start_trade_date = next_trading_date(seed_trade_dates[-1])
    target_trade_date = _calendar_target_trade_date()
    if start_trade_date > target_trade_date or not symbols:
        return []

    history_client = TencentQuoteClient()
    bars_by_symbol: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        bars = history_client.fetch_daily_bars_sync(
            symbol,
            start_trade_date=start_trade_date,
            end_trade_date=target_trade_date,
        )
        bars_by_symbol[symbol] = {bar.trade_date: bar for bar in bars}

    synced_trade_dates: list[str] = []
    previous_close_by_symbol: dict[str, float] = {}
    for symbol in symbols:
        previous = market_repo.previous_eod_price(symbol, start_trade_date)
        previous_close_by_symbol[symbol] = previous.close_price if previous else 0.0

    current = start_trade_date
    while current < target_trade_date:
        current_bars = []
        for symbol in symbols:
            bar = bars_by_symbol.get(symbol, {}).get(current)
            if bar is None:
                return synced_trade_dates
            current_bars.append((symbol, bar))
        for symbol, bar in current_bars:
            previous_close = (
                previous_close_by_symbol.get(symbol)
                or bar.open_price
                or bar.close_price
            )
            market_repo.upsert_eod_price(
                symbol=symbol,
                symbol_name=bar.name,
                trade_date=current,
                close_price=bar.close_price,
                open_price=bar.open_price,
                previous_close=previous_close,
                high_price=bar.high_price,
                low_price=bar.low_price,
                is_final=True,
                source="tencent_raw_history",
                published_at=combine_market_datetime(current, "15:00:00"),
            )
            previous_close_by_symbol[symbol] = bar.close_price
        synced_trade_dates.append(current)
        current = next_trading_date(current)
    return synced_trade_dates


def _normalized_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        candidate = value.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _users_by_name(*, user_repo: UserRepository, name: str) -> list:
    return user_repo.list_by_name(name)


def restore_test_user(
    *,
    user_id: str = TEST_USER_ID,
    name: str = TEST_USER_NAME,
    initial_cash: float = TEST_INITIAL_CASH,
    delete_user_ids: Iterable[str] = (),
    delete_user_names: Iterable[str] = (),
) -> dict:
    require_postgres_confirmation(
        action="uv run python -m devtools.restore_test_user",
        confirm_env="ASHARE_CONFIRM_RESTORE_TEST_USER",
    )
    init_db()
    target_trade_date = _calendar_target_trade_date()
    trade_dates = sample_trade_dates_before(target_trade_date)
    delete_user_ids = _normalized_unique(delete_user_ids)
    delete_user_names = _normalized_unique(delete_user_names)

    with session_scope() as session:
        user_repo = UserRepository(session)
        order_repo = OrderRepository(session)
        portfolio_repo = PortfolioRepository(session)
        market_repo = MarketDataRepository(session)
        pnl_service = PnlService(session)
        query_service = QueryService(session)

        removed_users: list[dict[str, str]] = []
        removed_user_ids: set[str] = set()

        def queue_delete(user) -> None:
            if user is None or user.id in removed_user_ids:
                return
            removed_user_ids.add(user.id)
            removed_users.append({"id": user.id, "name": user.name})

        queue_delete(user_repo.get(user_id))

        for same_name_user in _users_by_name(user_repo=user_repo, name=name):
            if same_name_user.id != user_id:
                queue_delete(same_name_user)

        for doomed_user_id in delete_user_ids:
            if doomed_user_id != user_id:
                queue_delete(user_repo.get(doomed_user_id))

        for doomed_name in delete_user_names:
            if doomed_name != name:
                for doomed_user in _users_by_name(user_repo=user_repo, name=doomed_name):
                    queue_delete(doomed_user)

        for doomed_user_id in removed_user_ids:
            user_repo.delete(doomed_user_id)

        user_repo.create(user_id=user_id, name=name, initial_cash=initial_cash)
        seed_trades(
            order_repo=order_repo,
            portfolio_repo=portfolio_repo,
            user_id=user_id,
            initial_cash=initial_cash,
            as_of_trade_date=target_trade_date,
        )
        seed_market_data(market_repo=market_repo, trade_dates=trade_dates)

        for trade_date in trade_dates:
            pnl_service.recompute_daily_pnl(
                user_id, trade_date, use_realtime=False, is_final=True
            )
        tracked_symbols = _tracked_symbols(
            portfolio_repo=portfolio_repo,
            user_id=user_id,
        )
        quote_trade_dates = _sync_latest_quotes(
            market_repo=market_repo,
            symbols=tracked_symbols,
        )
        extended_trade_dates = _sync_historical_eod_prices(
            market_repo=market_repo,
            symbols=tracked_symbols,
            seed_trade_dates=trade_dates,
        )
        for trade_date in extended_trade_dates:
            pnl_service.recompute_daily_pnl(
                user_id,
                trade_date,
                use_realtime=False,
                is_final=True,
            )

        current_trade_date = _calendar_target_trade_date()
        market_session = market_clock.get_session()
        if current_trade_date in quote_trade_dates:
            can_finalize = pnl_service.materialize_trade_date_eod_prices(
                user_id,
                current_trade_date,
                is_final=market_session.market_status == "closed",
                source="tencent_quote",
            )
            pnl_service.recompute_daily_pnl(
                user_id,
                current_trade_date,
                use_realtime=market_session.market_status != "closed",
                is_final=can_finalize and market_session.market_status == "closed",
            )

        dashboard = query_service.get_dashboard(user_id)
        positions = query_service.get_positions(user_id)
        history = query_service.get_history(user_id)
        calendar = query_service.get_calendar(user_id)

    return {
        "restoredUser": {"id": user_id, "name": name, "initialCash": initial_cash},
        "removedUsers": removed_users,
        "seededTradeDates": trade_dates,
        "quoteTradeDates": quote_trade_dates,
        "extendedTradeDates": extended_trade_dates,
        "counts": {
            "positions": len(positions),
            "history": len(history),
            "calendar": len(calendar),
        },
        "dashboard": dashboard,
    }


def main() -> None:
    summary = restore_test_user()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
