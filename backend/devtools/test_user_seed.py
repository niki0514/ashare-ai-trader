from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.quote_client import to_quote_symbol
from app.repositories import MarketDataRepository, OrderRepository, PortfolioRepository


TEST_USER_ID = "test-user"
TEST_USER_NAME = "Test User"
TEST_INITIAL_CASH = 500000.0


@dataclass(slots=True)
class SampleTrade:
    trade_time: str
    symbol: str
    name: str
    side: str
    order_price: float
    fill_price: float
    lots: int
    shares: int


@dataclass(slots=True)
class SampleReferenceQuote:
    symbol: str
    name: str
    price: float
    previous_close: float


SAMPLE_CLOSE_PRICES: dict[str, dict[str, float]] = {
    "2026-03-16": {
        "000021": 33.10,
        "000547": 31.87,
    },
    "2026-03-17": {
        "000021": 32.26,
        "000547": 30.49,
    },
    "2026-03-18": {
        "000021": 33.63,
        "000547": 31.40,
    },
    "2026-03-19": {
        "000021": 32.43,
        "000547": 30.36,
    },
}

SAMPLE_TRADES: list[SampleTrade] = [
    SampleTrade(
        "2026-03-16 09:45:00", "000547", "航天发展", "BUY", 30.90, 30.90, 70, 7000
    ),
    SampleTrade(
        "2026-03-16 10:02:00", "000021", "深科技", "BUY", 31.13, 31.13, 60, 6000
    ),
    SampleTrade(
        "2026-03-16 10:30:00", "000021", "深科技", "BUY", 31.39, 31.39, 10, 1000
    ),
    SampleTrade(
        "2026-03-16 10:56:00", "000547", "航天发展", "BUY", 30.98, 30.98, 10, 1000
    ),
    SampleTrade(
        "2026-03-17 10:00:00", "000547", "航天发展", "SELL", 31.66, 31.66, 40, 4000
    ),
    SampleTrade(
        "2026-03-17 13:28:00", "000547", "航天发展", "BUY", 31.11, 31.11, 10, 1000
    ),
    SampleTrade(
        "2026-03-17 14:00:00", "000021", "深科技", "SELL", 32.47, 32.47, 30, 3000
    ),
    SampleTrade(
        "2026-03-18 09:35:00", "000547", "航天发展", "BUY", 30.35, 30.35, 10, 1000
    ),
    SampleTrade(
        "2026-03-18 10:30:00", "000021", "深科技", "BUY", 32.94, 32.94, 10, 1000
    ),
    SampleTrade(
        "2026-03-18 14:20:00", "000021", "深科技", "SELL", 33.70, 33.70, 40, 4000
    ),
    SampleTrade(
        "2026-03-18 14:30:00", "000547", "航天发展", "SELL", 31.67, 31.67, 20, 2000
    ),
    SampleTrade(
        "2026-03-26 09:41:03", "000021", "深科技", "SELL", 28.80, 28.80, 10, 1000
    ),
]

SAMPLE_REFERENCE_QUOTES: list[SampleReferenceQuote] = [
    SampleReferenceQuote("600519", "贵州茅台", 1658.00, 1642.30),
    SampleReferenceQuote("000858", "五粮液", 130.00, 128.52),
]


def parse_trade_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def sample_trade_dates_before(as_of_trade_date: str | None = None) -> list[str]:
    dates = sorted(SAMPLE_CLOSE_PRICES.keys())
    if as_of_trade_date is None:
        return dates
    return [trade_date for trade_date in dates if trade_date < as_of_trade_date]


def sample_trades_before(as_of_trade_date: str | None = None) -> list[SampleTrade]:
    if as_of_trade_date is None:
        return list(SAMPLE_TRADES)
    return [
        trade
        for trade in SAMPLE_TRADES
        if parse_trade_time(trade.trade_time).date().isoformat() <= as_of_trade_date
    ]


def event_times_for_trade(trade_time: datetime) -> dict[str, datetime]:
    created_at = trade_time - timedelta(minutes=10)
    pending_at = trade_time - timedelta(minutes=5)
    return {
        "created": created_at,
        "pending": pending_at,
        "triggered": trade_time,
        "filled": trade_time,
    }


def seed_market_data(
    *,
    market_repo: MarketDataRepository,
    trade_dates: list[str],
) -> None:
    if not trade_dates:
        return

    for day_idx, trade_date in enumerate(trade_dates):
        for symbol, close_price in SAMPLE_CLOSE_PRICES[trade_date].items():
            previous_close = close_price
            if day_idx > 0:
                previous_close = SAMPLE_CLOSE_PRICES[trade_dates[day_idx - 1]].get(
                    symbol, close_price
                )
            market_repo.upsert_eod_price(
                symbol=symbol,
                symbol_name="深科技" if symbol == "000021" else "航天发展",
                trade_date=trade_date,
                close_price=close_price,
                open_price=close_price,
                previous_close=previous_close,
                high_price=close_price,
                low_price=close_price,
                is_final=True,
                source="test_seed",
                published_at=parse_trade_time(f"{trade_date} 15:00:00"),
            )

    latest_day = trade_dates[-1]
    for symbol, close_price in SAMPLE_CLOSE_PRICES[latest_day].items():
        previous_close = (
            SAMPLE_CLOSE_PRICES[trade_dates[-2]].get(symbol, close_price)
            if len(trade_dates) > 1
            else close_price
        )
        market_repo.append_intraday_quote(
            {
                "symbol": to_quote_symbol(symbol),
                "name": "深科技" if symbol == "000021" else "航天发展",
                "trade_date": latest_day,
                "price": close_price,
                "open": close_price,
                "previousClose": previous_close,
                "high": close_price,
                "low": close_price,
                "quoted_at": parse_trade_time(f"{latest_day} 15:00:00"),
                "source": "test_seed",
            }
        )

    for reference in SAMPLE_REFERENCE_QUOTES:
        market_repo.append_intraday_quote(
            {
                "symbol": to_quote_symbol(reference.symbol),
                "name": reference.name,
                "trade_date": "2026-03-19",
                "price": reference.price,
                "open": reference.price,
                "previousClose": reference.previous_close,
                "high": reference.price,
                "low": reference.price,
                "quoted_at": parse_trade_time("2026-03-19 15:00:00"),
                "source": "test_reference",
            }
        )


def seed_trades(
    *,
    order_repo: OrderRepository,
    portfolio_repo: PortfolioRepository,
    user_id: str,
    initial_cash: float,
    as_of_trade_date: str | None = None,
) -> None:
    trades = sample_trades_before(as_of_trade_date)
    if not trades:
        return

    first_time = parse_trade_time(trades[0].trade_time)
    initial_time = first_time - timedelta(minutes=1)
    portfolio_repo.add_cash_entry(
        user_id=user_id,
        entry_time=initial_time,
        entry_type="INITIAL",
        amount=initial_cash,
        reference_type="TestAccountBootstrap",
    )

    current_trade_date: str | None = None
    for trade in trades:
        fill_time = parse_trade_time(trade.trade_time)
        trade_date = fill_time.strftime("%Y-%m-%d")
        if current_trade_date != trade_date:
            current_trade_date = trade_date
            portfolio_repo.unlock_previous_lots(user_id, trade_date)

        timestamps = event_times_for_trade(fill_time)
        order = order_repo.create_order(
            user_id=user_id,
            trade_date=trade_date,
            symbol=trade.symbol,
            symbol_name=trade.name,
            side=trade.side,
            limit_price=trade.order_price,
            lots=trade.lots,
            validity="DAY",
            status="filled",
            status_reason="成交完成",
            created_at=timestamps["created"],
        )
        order_repo.add_event(order.id, "confirmed", "待执行", timestamps["created"])
        order_repo.add_event(order.id, "pending", "等待触发", timestamps["pending"])
        order_repo.add_event(
            order.id,
            "triggered",
            f"盘中价格达到{'买入' if trade.side == 'BUY' else '卖出'}条件",
            timestamps["triggered"],
        )

        available_cash = portfolio_repo.cash_balance(user_id)

        if trade.side == "BUY":
            amount = trade.fill_price * trade.shares
            cash_after = available_cash - amount
            open_shares = sum(
                lot.remaining_shares
                for lot in portfolio_repo.open_lots(user_id, trade.symbol)
            )
            created_trade = order_repo.create_trade(
                user_id=user_id,
                order_id=order.id,
                symbol=trade.symbol,
                side=trade.side,
                order_price=trade.order_price,
                fill_price=trade.fill_price,
                cost_basis_amount=amount,
                realized_pnl=0,
                lots=trade.lots,
                shares=trade.shares,
                fill_time=fill_time,
                cash_after=cash_after,
                position_after=open_shares + trade.shares,
            )
            order_repo.add_event(
                order.id,
                "filled",
                f"按 {trade.fill_price:.2f} 成交",
                timestamps["filled"],
            )
            order_repo.update_order_status(
                order,
                status="filled",
                status_reason="成交完成",
                triggered_at=timestamps["triggered"],
                filled_at=timestamps["filled"],
            )
            portfolio_repo.add_cash_entry(
                user_id=user_id,
                entry_time=fill_time,
                entry_type="BUY",
                amount=-amount,
                reference_id=created_trade.id,
                reference_type="ExecutionTrade",
            )
            portfolio_repo.create_position_lot(
                user_id=user_id,
                symbol=trade.symbol,
                symbol_name=trade.name,
                opened_order_id=order.id,
                opened_trade_id=created_trade.id,
                opened_date=trade_date,
                opened_at=fill_time,
                cost_price=trade.fill_price,
                original_shares=trade.shares,
                remaining_shares=trade.shares,
                sellable_shares=0,
            )
            continue

        amount = trade.fill_price * trade.shares
        remaining_to_sell = trade.shares
        cost_basis_amount = 0.0
        position_after = 0
        for lot in portfolio_repo.open_lots(user_id, trade.symbol):
            if remaining_to_sell <= 0:
                position_after += lot.remaining_shares
                continue
            consumed = min(lot.remaining_shares, remaining_to_sell)
            remaining = lot.remaining_shares - consumed
            cost_basis_amount += consumed * lot.cost_price
            remaining_to_sell -= consumed
            portfolio_repo.update_lot(
                lot,
                remaining_shares=remaining,
                sellable_shares=remaining,
                closed_at=fill_time if remaining == 0 else None,
            )
            position_after += remaining
        if remaining_to_sell != 0:
            raise ValueError(f"Insufficient seeded position for {trade.symbol}")

        cash_after = available_cash + amount
        realized_pnl = amount - cost_basis_amount
        created_trade = order_repo.create_trade(
            user_id=user_id,
            order_id=order.id,
            symbol=trade.symbol,
            side=trade.side,
            order_price=trade.order_price,
            fill_price=trade.fill_price,
            cost_basis_amount=cost_basis_amount,
            realized_pnl=realized_pnl,
            lots=trade.lots,
            shares=trade.shares,
            fill_time=fill_time,
            cash_after=cash_after,
            position_after=position_after,
        )
        order_repo.add_event(
            order.id, "filled", f"按 {trade.fill_price:.2f} 成交", timestamps["filled"]
        )
        order_repo.update_order_status(
            order,
            status="filled",
            status_reason="成交完成",
            triggered_at=timestamps["triggered"],
            filled_at=timestamps["filled"],
        )
        portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=fill_time,
            entry_type="SELL",
            amount=amount,
            reference_id=created_trade.id,
            reference_type="ExecutionTrade",
        )
