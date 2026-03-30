from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import delete, func, select

from app.db import session_scope
from app.market import market_clock, next_trading_date, previous_trading_date
from app.models import DailyPnl, DailyPnlDetail, EodPrice, ExecutionTrade
from app.quote_client import TencentQuoteClient
from app.repositories import MarketDataRepository, UserRepository
from app.services import PnlService, SettlementService
from app.time_utils import combine_market_datetime
from devtools.schema import init_db
from devtools.safety import require_postgres_confirmation


@dataclass(slots=True)
class RebuildScope:
    user_ids: list[str]
    symbols: list[str]
    historical_start_trade_date: str | None


def _historical_target_trade_date() -> str:
    session = market_clock.get_session()
    if session.market_status == "closed":
        return session.trade_date
    return previous_trading_date(session.trade_date)


def _load_scope() -> RebuildScope:
    with session_scope() as session:
        user_ids = UserRepository(session).list_user_ids()
        symbols = sorted(
            session.scalars(select(ExecutionTrade.symbol).distinct()).all()
        )
        start_trade_date = session.scalar(
            select(func.min(ExecutionTrade.fill_time))
        )

    return RebuildScope(
        user_ids=user_ids,
        symbols=[symbol for symbol in symbols if symbol],
        historical_start_trade_date=(
            start_trade_date.date().isoformat() if start_trade_date is not None else None
        ),
    )


def _rebuild_eod_prices(
    *,
    market_repo: MarketDataRepository,
    symbols: list[str],
    start_trade_date: str,
    end_trade_date: str,
) -> int:
    if start_trade_date > end_trade_date or not symbols:
        return 0

    history_client = TencentQuoteClient()
    bars_by_symbol: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        bars = history_client.fetch_daily_bars_sync(
            symbol,
            start_trade_date=start_trade_date,
            end_trade_date=end_trade_date,
        )
        bars_by_symbol[symbol] = {bar.trade_date: bar for bar in bars}

    current = start_trade_date
    inserted = 0
    previous_close_by_symbol: dict[str, float] = {}
    while current <= end_trade_date:
        current_bars = []
        for symbol in symbols:
            bar = bars_by_symbol.get(symbol, {}).get(current)
            if bar is not None:
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
            inserted += 1

        current = next_trading_date(current)

    return inserted


def rebuild_derived_data() -> dict:
    require_postgres_confirmation(
        action="uv run python -m devtools.rebuild_derived_data",
        confirm_env="ASHARE_CONFIRM_REBUILD_DERIVED_DATA",
    )
    init_db()
    scope = _load_scope()

    with session_scope() as session:
        session.execute(delete(DailyPnlDetail))
        session.execute(delete(DailyPnl))
        session.execute(delete(EodPrice))

    if not scope.user_ids or not scope.symbols or scope.historical_start_trade_date is None:
        return {
            "users": scope.user_ids,
            "symbols": scope.symbols,
            "rebuiltTradeDates": 0,
            "rebuiltEodRows": 0,
        }

    historical_target_trade_date = _historical_target_trade_date()
    rebuilt_eod_rows = 0
    with session_scope() as session:
        rebuilt_eod_rows = _rebuild_eod_prices(
            market_repo=MarketDataRepository(session),
            symbols=scope.symbols,
            start_trade_date=scope.historical_start_trade_date,
            end_trade_date=historical_target_trade_date,
        )

    rebuilt_trade_dates = 0
    with session_scope() as session:
        pnl_service = PnlService(session)
        settlement = SettlementService(session)
        session_info = market_clock.get_session()

        for user_id in scope.user_ids:
            user_start_trade_date = session.scalar(
                select(func.min(ExecutionTrade.fill_time)).where(
                    ExecutionTrade.user_id == user_id
                )
            )
            user_start_text = (
                user_start_trade_date.date().isoformat()
                if user_start_trade_date is not None
                else None
            )

            if not user_start_text:
                continue

            current = user_start_text
            while current <= historical_target_trade_date:
                pnl_service.recompute_daily_pnl(
                    user_id,
                    current,
                    use_realtime=False,
                    is_final=True,
                    persist=True,
                )
                rebuilt_trade_dates += 1
                current = next_trading_date(current)

            settlement.ensure_session_snapshot(user_id, session_info)

    return {
        "users": scope.user_ids,
        "symbols": scope.symbols,
        "rebuiltTradeDates": rebuilt_trade_dates,
        "rebuiltEodRows": rebuilt_eod_rows,
        "historicalStartTradeDate": scope.historical_start_trade_date,
        "historicalTargetTradeDate": historical_target_trade_date,
        "marketSession": asdict(market_clock.get_session()),
    }


def main() -> None:
    print(json.dumps(rebuild_derived_data(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
