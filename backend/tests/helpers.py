from __future__ import annotations

from datetime import datetime

from app.repositories import OrderRepository, PortfolioRepository
from app.trade_execution import record_buy_execution, record_sell_execution


def create_filled_buy_position(
    *,
    order_repo: OrderRepository,
    portfolio_repo: PortfolioRepository,
    user_id: str,
    trade_date: str,
    fill_time: datetime,
    symbol: str,
    symbol_name: str,
    price: float,
    lots: int,
    validity: str = "DAY",
    sellable_shares: int = 0,
):
    order = order_repo.create_order(
        user_id=user_id,
        trade_date=trade_date,
        symbol=symbol,
        symbol_name=symbol_name,
        side="BUY",
        limit_price=price,
        lots=lots,
        validity=validity,
        status="filled",
        status_reason="成交完成",
        created_at=fill_time,
    )
    trade = record_buy_execution(
        order_repo=order_repo,
        portfolio_repo=portfolio_repo,
        user_id=user_id,
        order=order,
        fill_price=price,
        fill_time=fill_time,
    )
    order_repo.update_order_status(
        order,
        status="filled",
        status_reason="成交完成",
        triggered_at=fill_time,
        filled_at=fill_time,
    )
    lot = next(
        lot
        for lot in portfolio_repo.open_lots(user_id, symbol)
        if lot.opened_trade_id == trade.id
    )
    if sellable_shares != lot.sellable_shares:
        portfolio_repo.update_lot(
            lot,
            remaining_shares=lot.remaining_shares,
            sellable_shares=sellable_shares,
        )
    return order, trade, lot


def create_filled_sell_execution(
    *,
    order_repo: OrderRepository,
    portfolio_repo: PortfolioRepository,
    user_id: str,
    trade_date: str,
    fill_time: datetime,
    symbol: str,
    symbol_name: str,
    price: float,
    lots: int,
    validity: str = "DAY",
):
    order = order_repo.create_order(
        user_id=user_id,
        trade_date=trade_date,
        symbol=symbol,
        symbol_name=symbol_name,
        side="SELL",
        limit_price=price,
        lots=lots,
        validity=validity,
        status="filled",
        status_reason="成交完成",
        created_at=fill_time,
    )
    trade = record_sell_execution(
        order_repo=order_repo,
        portfolio_repo=portfolio_repo,
        user_id=user_id,
        order=order,
        fill_price=price,
        fill_time=fill_time,
    )
    order_repo.update_order_status(
        order,
        status="filled",
        status_reason="成交完成",
        triggered_at=fill_time,
        filled_at=fill_time,
    )
    return order, trade
