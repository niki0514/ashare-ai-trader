from __future__ import annotations

from datetime import datetime

from .models import ExecutionTrade, InstructionOrder
from .repositories import OrderRepository, PortfolioRepository


def record_buy_execution(
    *,
    order_repo: OrderRepository,
    portfolio_repo: PortfolioRepository,
    user_id: str,
    order: InstructionOrder,
    fill_price: float,
    fill_time: datetime,
) -> ExecutionTrade:
    available_cash = portfolio_repo.cash_balance(user_id)
    amount = fill_price * order.shares
    if available_cash < amount:
        raise ValueError("Insufficient cash for buy execution")

    open_shares = sum(
        lot.remaining_shares for lot in portfolio_repo.open_lots(user_id, order.symbol)
    )
    trade = order_repo.create_trade(
        user_id=user_id,
        order_id=order.id,
        symbol=order.symbol,
        side=order.side.value,
        order_price=order.limit_price,
        fill_price=fill_price,
        cost_basis_amount=amount,
        realized_pnl=0.0,
        lots=order.lots,
        shares=order.shares,
        fill_time=fill_time,
        cash_after=available_cash - amount,
        position_after=open_shares + order.shares,
    )
    portfolio_repo.create_position_lot(
        user_id=user_id,
        symbol=order.symbol,
        symbol_name=order.symbol_name,
        opened_order_id=order.id,
        opened_trade_id=trade.id,
        opened_date=fill_time.date().isoformat(),
        opened_at=fill_time,
        cost_price=fill_price,
        original_shares=order.shares,
        remaining_shares=order.shares,
        sellable_shares=0,
    )
    portfolio_repo.add_trade_cash_entry(
        user_id=user_id,
        entry_time=fill_time,
        entry_type="BUY",
        amount=-amount,
        reference_id=trade.id,
    )
    return trade


def record_sell_execution(
    *,
    order_repo: OrderRepository,
    portfolio_repo: PortfolioRepository,
    user_id: str,
    order: InstructionOrder,
    fill_price: float,
    fill_time: datetime,
) -> ExecutionTrade:
    lots = [
        lot
        for lot in portfolio_repo.open_lots(user_id, order.symbol)
        if lot.sellable_shares > 0
    ]
    remaining = order.shares
    consumed_cost = 0.0
    for lot in lots:
        if remaining <= 0:
            break
        consumed = min(lot.sellable_shares, remaining)
        remaining -= consumed
        consumed_cost += consumed * lot.cost_price
        next_remaining = lot.remaining_shares - consumed
        portfolio_repo.update_lot(
            lot,
            remaining_shares=next_remaining,
            sellable_shares=lot.sellable_shares - consumed,
            closed_at=fill_time if next_remaining == 0 else None,
        )

    if remaining != 0:
        raise ValueError(f"Insufficient sellable position for {order.symbol}")

    available_cash = portfolio_repo.cash_balance(user_id)
    amount = fill_price * order.shares
    position_after = sum(
        lot.remaining_shares for lot in portfolio_repo.open_lots(user_id, order.symbol)
    )
    realized_pnl = amount - consumed_cost
    trade = order_repo.create_trade(
        user_id=user_id,
        order_id=order.id,
        symbol=order.symbol,
        side=order.side.value,
        order_price=order.limit_price,
        fill_price=fill_price,
        cost_basis_amount=consumed_cost,
        realized_pnl=realized_pnl,
        lots=order.lots,
        shares=order.shares,
        fill_time=fill_time,
        cash_after=available_cash + amount,
        position_after=position_after,
    )
    portfolio_repo.add_trade_cash_entry(
        user_id=user_id,
        entry_time=fill_time,
        entry_type="SELL",
        amount=amount,
        reference_id=trade.id,
    )
    return trade
