from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    CashEntryType,
    CashLedger,
    DailyPnl,
    DailyPnlDetail,
    EodPrice,
    ExecutionTrade,
    ImportBatch,
    ImportBatchItem,
    ImportBatchStatus,
    ImportMode,
    ImportSourceType,
    IntradayQuote,
    InstructionOrder,
    OrderEvent,
    OrderSide,
    OrderStatus,
    OrderValidity,
    PositionLot,
    PositionStatus,
    User,
    ValidationStatus,
)
from .time_utils import market_now


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


@dataclass(slots=True)
class SellAvailability:
    sellable_by_symbol: dict[str, int]
    reserved_by_symbol: dict[str, int]
    available_by_symbol: dict[str, int]


EXECUTABLE_ORDER_STATUSES = (OrderStatus.confirmed, OrderStatus.pending)
ACTIVE_ORDER_STATUSES = (
    OrderStatus.confirmed,
    OrderStatus.pending,
    OrderStatus.triggered,
)


def effective_order_clause(trade_date: str):
    return or_(
        InstructionOrder.trade_date == trade_date,
        and_(
            InstructionOrder.validity == OrderValidity.GTC,
            InstructionOrder.trade_date < trade_date,
        ),
    )


def is_order_effective_on_trade_date(order: InstructionOrder, trade_date: str) -> bool:
    return order.trade_date == trade_date or (
        order.validity == OrderValidity.GTC and order.trade_date < trade_date
    )


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, user_id: str) -> User | None:
        return self.session.get(User, user_id)

    def get_by_name(self, name: str) -> User | None:
        stmt = select(User).where(User.name == name)
        return self.session.scalar(stmt)

    def create(
        self, *, name: str, initial_cash: float, user_id: str | None = None
    ) -> User:
        user = User(id=user_id or new_id("usr"), name=name, initial_cash=initial_cash)
        self.session.add(user)
        self.session.flush()
        return user

    def list_users(self) -> list[User]:
        stmt = select(User).order_by(User.created_at.asc(), User.id.asc())
        return list(self.session.scalars(stmt).all())

    def list_user_ids(self) -> list[str]:
        stmt = select(User.id).order_by(User.created_at.asc(), User.id.asc())
        return list(self.session.scalars(stmt).all())

    def delete(self, user_id: str) -> None:
        user = self.get(user_id)
        if not user:
            return
        self.session.delete(user)
        self.session.flush()


class OrderRepository:
    def __init__(self, session: Session):
        self.session = session

    def count_orders(self, user_id: str) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(InstructionOrder)
                .where(InstructionOrder.user_id == user_id)
            )
            or 0
        )

    def get_order(self, order_id: str) -> InstructionOrder | None:
        return self.session.get(InstructionOrder, order_id)

    def delete_order(self, order: InstructionOrder) -> None:
        self.session.delete(order)
        self.session.flush()

    def list_orders(
        self, user_id: str, statuses: Iterable[OrderStatus] | None = None
    ) -> list[InstructionOrder]:
        stmt = select(InstructionOrder).where(InstructionOrder.user_id == user_id)
        if statuses:
            stmt = stmt.where(InstructionOrder.status.in_(list(statuses)))
        stmt = stmt.options(
            selectinload(InstructionOrder.events), selectinload(InstructionOrder.trades)
        ).order_by(InstructionOrder.updated_at.desc())
        return list(self.session.scalars(stmt).unique().all())

    def list_pending_orders(
        self, user_id: str, trade_date: str
    ) -> list[InstructionOrder]:
        stmt = (
            select(InstructionOrder)
            .where(
                InstructionOrder.user_id == user_id,
                InstructionOrder.status.in_(EXECUTABLE_ORDER_STATUSES),
                effective_order_clause(trade_date),
            )
            .order_by(InstructionOrder.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def list_conflict_sell_orders(
        self, user_id: str, trade_date: str
    ) -> list[InstructionOrder]:
        stmt = (
            select(InstructionOrder)
            .where(
                InstructionOrder.user_id == user_id,
                InstructionOrder.side == OrderSide.SELL,
                InstructionOrder.status.in_(EXECUTABLE_ORDER_STATUSES),
                effective_order_clause(trade_date),
            )
            .order_by(InstructionOrder.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def list_day_orders_to_expire(
        self, user_id: str, trade_date: str
    ) -> list[InstructionOrder]:
        stmt = select(InstructionOrder).where(
            InstructionOrder.user_id == user_id,
            InstructionOrder.trade_date == trade_date,
            InstructionOrder.validity == OrderValidity.DAY,
            InstructionOrder.status.in_(
                [OrderStatus.confirmed, OrderStatus.pending, OrderStatus.triggered]
            ),
        )
        return list(self.session.scalars(stmt).all())

    def list_confirmed_orders(
        self, user_id: str, trade_date: str
    ) -> list[InstructionOrder]:
        stmt = select(InstructionOrder).where(
            InstructionOrder.user_id == user_id,
            InstructionOrder.status == OrderStatus.confirmed,
            effective_order_clause(trade_date),
        )
        return list(self.session.scalars(stmt).all())

    def create_order(
        self,
        *,
        user_id: str,
        trade_date: str,
        symbol: str,
        symbol_name: str | None,
        side: str,
        limit_price: float,
        lots: int,
        validity: str,
        status: str = "confirmed",
        status_reason: str = "待执行",
        created_at: datetime | None = None,
    ) -> InstructionOrder:
        now = created_at or market_now()
        order = InstructionOrder(
            id=new_id("ord"),
            user_id=user_id,
            trade_date=trade_date,
            symbol=symbol,
            symbol_name=symbol_name,
            side=OrderSide(side),
            limit_price=limit_price,
            lots=lots,
            shares=lots * 100,
            validity=OrderValidity(validity),
            status=OrderStatus(status),
            status_reason=status_reason,
            created_at=now,
            updated_at=now,
        )
        self.session.add(order)
        self.session.flush()
        return order

    def add_event(
        self,
        order_id: str,
        event_type: str,
        message: str,
        event_time: datetime | None = None,
    ) -> OrderEvent:
        event = OrderEvent(
            id=new_id("evt"),
            order_id=order_id,
            event_type=OrderStatus(event_type),
            event_time=event_time or market_now(),
            message=message,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def update_order_status(
        self,
        order: InstructionOrder,
        *,
        status: str,
        status_reason: str,
        triggered_at: datetime | None = None,
        filled_at: datetime | None = None,
    ) -> None:
        order.status = OrderStatus(status)
        order.status_reason = status_reason
        order.updated_at = market_now()
        if triggered_at is not None:
            order.triggered_at = triggered_at
        if filled_at is not None:
            order.filled_at = filled_at
        self.session.flush()

    def create_trade(
        self,
        *,
        user_id: str,
        order_id: str,
        symbol: str,
        side: str,
        order_price: float,
        fill_price: float,
        cost_basis_amount: float,
        realized_pnl: float,
        lots: int,
        shares: int,
        fill_time: datetime,
        cash_after: float,
        position_after: int,
    ) -> ExecutionTrade:
        trade = ExecutionTrade(
            id=new_id("trd"),
            user_id=user_id,
            order_id=order_id,
            symbol=symbol,
            side=OrderSide(side),
            order_price=order_price,
            fill_price=fill_price,
            cost_basis_amount=cost_basis_amount,
            realized_pnl=realized_pnl,
            lots=lots,
            shares=shares,
            fill_time=fill_time,
            cash_after=cash_after,
            position_after=position_after,
        )
        self.session.add(trade)
        self.session.flush()
        return trade

    def latest_import_batches(
        self, user_id: str, trade_date: str | None = None
    ) -> list[ImportBatch]:
        stmt = select(ImportBatch).where(ImportBatch.user_id == user_id)
        if trade_date:
            stmt = stmt.where(ImportBatch.target_trade_date == trade_date)
        stmt = (
            stmt.options(selectinload(ImportBatch.items))
            .order_by(ImportBatch.created_at.desc())
            .limit(5)
        )
        return list(self.session.scalars(stmt).unique().all())

    def delete_draft_import_batches(self, user_id: str, trade_date: str) -> int:
        stmt = (
            select(ImportBatch)
            .where(
                ImportBatch.user_id == user_id,
                ImportBatch.target_trade_date == trade_date,
                ImportBatch.mode == ImportMode.DRAFT,
            )
            .options(selectinload(ImportBatch.items))
        )
        batches = list(self.session.scalars(stmt).unique().all())
        for batch in batches:
            self.session.delete(batch)
        self.session.flush()
        return len(batches)

    def create_import_batch(
        self,
        *,
        user_id: str,
        target_trade_date: str,
        source_type: str,
        file_name: str | None,
        mode: str,
        rows: list[dict],
    ) -> ImportBatch:
        batch = ImportBatch(
            id=new_id("imp"),
            user_id=user_id,
            target_trade_date=target_trade_date,
            source_type=ImportSourceType(source_type),
            file_name=file_name,
            mode=ImportMode(mode),
            status=ImportBatchStatus.VALIDATED,
        )
        self.session.add(batch)
        self.session.flush()
        for row in rows:
            item = ImportBatchItem(
                id=new_id("impi"),
                batch_id=batch.id,
                row_number=row["rowNumber"],
                symbol=row["symbol"],
                symbol_name=row.get("name"),
                side=OrderSide(row["side"]),
                limit_price=row["price"],
                lots=row["lots"],
                validity=OrderValidity(row["validity"]),
                validation_status=ValidationStatus(row["validationStatus"]),
                validation_message=row["validationMessage"],
            )
            self.session.add(item)
        self.session.flush()
        self.session.refresh(batch)
        return batch

    def get_import_batch(self, batch_id: str) -> ImportBatch | None:
        stmt = (
            select(ImportBatch)
            .where(ImportBatch.id == batch_id)
            .options(selectinload(ImportBatch.items))
        )
        return self.session.scalar(stmt)

    def commit_import_batch(self, batch: ImportBatch, mode: str) -> int:
        if mode == ImportMode.OVERWRITE.value:
            self.session.execute(
                delete(InstructionOrder).where(
                    InstructionOrder.user_id == batch.user_id,
                    InstructionOrder.trade_date == batch.target_trade_date,
                    InstructionOrder.status.in_(ACTIVE_ORDER_STATUSES),
                )
            )
        imported_count = 0
        if mode != ImportMode.DRAFT.value:
            if any(
                item.validation_status == ValidationStatus.ERROR for item in batch.items
            ):
                raise ValueError("导入批次校验已变化，请重新校验后再提交")
            for item in batch.items:
                self.create_order(
                    user_id=batch.user_id,
                    trade_date=batch.target_trade_date,
                    symbol=item.symbol,
                    symbol_name=item.symbol_name,
                    side=item.side.value,
                    limit_price=item.limit_price,
                    lots=item.lots,
                    validity=item.validity.value,
                )
                imported_count += 1
        batch.status = (
            ImportBatchStatus.VALIDATED
            if mode == ImportMode.DRAFT.value
            else ImportBatchStatus.COMMITTED
        )
        batch.mode = ImportMode(mode)
        self.session.flush()
        return imported_count


class PortfolioRepository:
    def __init__(self, session: Session):
        self.session = session

    def latest_cash(
        self, user_id: str, before: datetime | None = None
    ) -> CashLedger | None:
        stmt = select(CashLedger).where(CashLedger.user_id == user_id)
        if before is not None:
            stmt = stmt.where(CashLedger.entry_time <= before)
        stmt = stmt.order_by(CashLedger.entry_time.desc())
        return self.session.scalar(stmt)

    def cash_balance(self, user_id: str, before: datetime | None = None) -> float:
        stmt = select(func.coalesce(func.sum(CashLedger.amount), 0.0)).where(
            CashLedger.user_id == user_id
        )
        if before is not None:
            stmt = stmt.where(CashLedger.entry_time <= before)
        total = self.session.scalar(stmt)
        return float(total or 0.0)

    def add_cash_entry(
        self,
        *,
        user_id: str,
        entry_time: datetime,
        entry_type: str,
        amount: float,
        reference_id: str | None = None,
        reference_type: str | None = None,
    ) -> CashLedger:
        row = CashLedger(
            id=new_id("cash"),
            user_id=user_id,
            entry_time=entry_time,
            entry_type=CashEntryType(entry_type),
            amount=amount,
            reference_id=reference_id,
            reference_type=reference_type,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def open_lots(self, user_id: str, symbol: str | None = None) -> list[PositionLot]:
        stmt = select(PositionLot).where(
            PositionLot.user_id == user_id, PositionLot.status == PositionStatus.OPEN
        )
        if symbol:
            stmt = stmt.where(PositionLot.symbol == symbol)
        stmt = stmt.order_by(PositionLot.opened_at.asc())
        return list(self.session.scalars(stmt).all())

    def all_lots(self, user_id: str) -> list[PositionLot]:
        stmt = (
            select(PositionLot)
            .where(PositionLot.user_id == user_id)
            .order_by(PositionLot.opened_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def create_position_lot(
        self,
        *,
        user_id: str,
        symbol: str,
        symbol_name: str | None,
        opened_order_id: str | None,
        opened_trade_id: str | None,
        opened_date: str,
        opened_at: datetime,
        cost_price: float,
        original_shares: int,
        remaining_shares: int,
        sellable_shares: int,
    ) -> PositionLot:
        lot = PositionLot(
            id=new_id("lot"),
            user_id=user_id,
            symbol=symbol,
            symbol_name=symbol_name,
            opened_order_id=opened_order_id,
            opened_trade_id=opened_trade_id,
            opened_date=opened_date,
            opened_at=opened_at,
            cost_price=cost_price,
            original_shares=original_shares,
            remaining_shares=remaining_shares,
            sellable_shares=sellable_shares,
            status=PositionStatus.OPEN,
        )
        self.session.add(lot)
        self.session.flush()
        return lot

    def update_lot(
        self,
        lot: PositionLot,
        *,
        remaining_shares: int,
        sellable_shares: int,
        closed_at: datetime | None = None,
    ) -> None:
        lot.remaining_shares = remaining_shares
        lot.sellable_shares = sellable_shares
        lot.status = (
            PositionStatus.CLOSED if remaining_shares == 0 else PositionStatus.OPEN
        )
        lot.closed_at = closed_at if remaining_shares == 0 else None
        self.session.flush()

    def unlock_previous_lots(self, user_id: str, trade_date: str) -> None:
        stmt = select(PositionLot).where(
            PositionLot.user_id == user_id,
            PositionLot.status == PositionStatus.OPEN,
            PositionLot.opened_date < trade_date,
        )
        for row in self.session.scalars(stmt).all():
            row.sellable_shares = row.remaining_shares
        self.session.flush()

    def get_pending_sell_orders_by_symbol(
        self, user_id: str, trade_date: str
    ) -> dict[str, list[InstructionOrder]]:
        stmt = (
            select(InstructionOrder)
            .where(
                InstructionOrder.user_id == user_id,
                InstructionOrder.side == OrderSide.SELL,
                InstructionOrder.status.in_(ACTIVE_ORDER_STATUSES),
                effective_order_clause(trade_date),
            )
            .order_by(InstructionOrder.created_at.asc())
        )
        grouped: dict[str, list[InstructionOrder]] = defaultdict(list)
        for row in self.session.scalars(stmt).all():
            grouped[row.symbol].append(row)
        return grouped

    def get_available_sellable_shares(
        self,
        user_id: str,
        trade_date: str,
        exclude_order_id: str | None = None,
    ) -> SellAvailability:
        sellable_by_symbol: dict[str, int] = defaultdict(int)
        for lot in self.open_lots(user_id):
            sellable_by_symbol[lot.symbol] += lot.sellable_shares

        reserved_stmt = select(InstructionOrder.symbol, InstructionOrder.shares).where(
            InstructionOrder.user_id == user_id,
            InstructionOrder.side == OrderSide.SELL,
            InstructionOrder.status.in_(ACTIVE_ORDER_STATUSES),
            effective_order_clause(trade_date),
        )
        if exclude_order_id:
            reserved_stmt = reserved_stmt.where(InstructionOrder.id != exclude_order_id)
        reserved_by_symbol: dict[str, int] = defaultdict(int)
        for symbol, shares in self.session.execute(reserved_stmt).all():
            reserved_by_symbol[symbol] += shares

        available_by_symbol = {
            symbol: max(
                0, sellable_by_symbol.get(symbol, 0) - reserved_by_symbol.get(symbol, 0)
            )
            for symbol in sellable_by_symbol
        }
        return SellAvailability(
            dict(sellable_by_symbol), dict(reserved_by_symbol), available_by_symbol
        )


class MarketDataRepository:
    def __init__(self, session: Session):
        self.session = session

    def delete_intraday_quotes(
        self, *, symbols: list[str] | None = None, trade_dates: list[str] | None = None
    ) -> None:
        stmt = delete(IntradayQuote)
        if symbols:
            stmt = stmt.where(IntradayQuote.symbol.in_(symbols))
        if trade_dates:
            stmt = stmt.where(IntradayQuote.trade_date.in_(trade_dates))
        self.session.execute(stmt)
        self.session.flush()

    def delete_eod_prices(
        self, *, symbols: list[str] | None = None, trade_dates: list[str] | None = None
    ) -> None:
        stmt = delete(EodPrice)
        if symbols:
            stmt = stmt.where(EodPrice.symbol.in_(symbols))
        if trade_dates:
            stmt = stmt.where(EodPrice.trade_date.in_(trade_dates))
        self.session.execute(stmt)
        self.session.flush()

    def append_intraday_quote(self, row: dict) -> IntradayQuote:
        stmt = select(IntradayQuote).where(
            IntradayQuote.symbol == row["symbol"],
            IntradayQuote.quoted_at == row["quoted_at"],
        )
        existing = self.session.scalar(stmt)
        if existing:
            existing.symbol_name = row["name"]
            existing.trade_date = row["trade_date"]
            existing.price = row["price"]
            existing.open_price = row["open"]
            existing.previous_close = row["previousClose"]
            existing.high_price = row["high"]
            existing.low_price = row["low"]
            existing.source = row.get("source")
            existing.ingested_at = market_now()
            self.session.flush()
            return existing

        quote = IntradayQuote(
            id=new_id("iq"),
            symbol=row["symbol"],
            symbol_name=row["name"],
            trade_date=row["trade_date"],
            quoted_at=row["quoted_at"],
            price=row["price"],
            open_price=row["open"],
            previous_close=row["previousClose"],
            high_price=row["high"],
            low_price=row["low"],
            source=row.get("source"),
        )
        self.session.add(quote)
        self.session.flush()
        return quote

    def latest_intraday_quote(
        self, symbol: str, trade_date: str | None = None
    ) -> IntradayQuote | None:
        stmt = select(IntradayQuote).where(IntradayQuote.symbol == symbol)
        if trade_date:
            stmt = stmt.where(IntradayQuote.trade_date == trade_date)
        stmt = stmt.order_by(IntradayQuote.quoted_at.desc(), IntradayQuote.id.desc())
        return self.session.scalar(stmt)

    def list_latest_intraday_quotes(
        self, symbols: list[str] | None = None, trade_date: str | None = None
    ) -> list[IntradayQuote]:
        latest_rows = (
            select(
                IntradayQuote.id,
                func.row_number()
                .over(
                    partition_by=IntradayQuote.symbol,
                    order_by=(
                        IntradayQuote.quoted_at.desc(),
                        IntradayQuote.id.desc(),
                    ),
                )
                .label("row_number"),
            )
        )
        if symbols:
            latest_rows = latest_rows.where(IntradayQuote.symbol.in_(sorted(set(symbols))))
        if trade_date:
            latest_rows = latest_rows.where(IntradayQuote.trade_date == trade_date)

        latest_rows_subquery = latest_rows.subquery()
        stmt = (
            select(IntradayQuote)
            .join(
                latest_rows_subquery,
                IntradayQuote.id == latest_rows_subquery.c.id,
            )
            .where(latest_rows_subquery.c.row_number == 1)
            .order_by(IntradayQuote.symbol.asc())
        )
        return list(self.session.scalars(stmt).all())

    def latest_intraday_updated_at(
        self, trade_date: str | None = None
    ) -> datetime | None:
        stmt = select(func.max(IntradayQuote.quoted_at))
        if trade_date:
            stmt = stmt.where(IntradayQuote.trade_date == trade_date)
        return self.session.scalar(stmt)

    def get_eod_price(self, symbol: str, trade_date: str) -> EodPrice | None:
        stmt = select(EodPrice).where(
            EodPrice.symbol == symbol, EodPrice.trade_date == trade_date
        )
        return self.session.scalar(stmt)

    def upsert_eod_price(
        self,
        *,
        symbol: str,
        symbol_name: str | None,
        trade_date: str,
        close_price: float,
        open_price: float = 0,
        previous_close: float = 0,
        high_price: float = 0,
        low_price: float = 0,
        is_final: bool = True,
        source: str | None = None,
        published_at: datetime | None = None,
    ) -> EodPrice:
        stmt = select(EodPrice).where(
            EodPrice.symbol == symbol, EodPrice.trade_date == trade_date
        )
        existing = self.session.scalar(stmt)
        if existing:
            existing.symbol_name = symbol_name
            existing.close_price = close_price
            existing.open_price = open_price
            existing.previous_close = previous_close
            existing.high_price = high_price
            existing.low_price = low_price
            existing.is_final = is_final
            existing.source = source
            existing.published_at = published_at or existing.published_at
            existing.updated_at = market_now()
            self.session.flush()
            return existing

        row = EodPrice(
            id=new_id("eod"),
            symbol=symbol,
            symbol_name=symbol_name,
            trade_date=trade_date,
            close_price=close_price,
            open_price=open_price,
            previous_close=previous_close,
            high_price=high_price,
            low_price=low_price,
            is_final=is_final,
            source=source,
            published_at=published_at or market_now(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def latest_eod_price(
        self, symbol: str, trade_date_lte: str | None = None
    ) -> EodPrice | None:
        stmt = select(EodPrice).where(EodPrice.symbol == symbol)
        if trade_date_lte:
            stmt = stmt.where(EodPrice.trade_date <= trade_date_lte)
        stmt = stmt.order_by(EodPrice.trade_date.desc())
        return self.session.scalar(stmt)

    def previous_eod_price(self, symbol: str, trade_date: str) -> EodPrice | None:
        stmt = (
            select(EodPrice)
            .where(EodPrice.symbol == symbol, EodPrice.trade_date < trade_date)
            .order_by(EodPrice.trade_date.desc())
        )
        return self.session.scalar(stmt)

    def list_eod_prices(self, trade_date: str) -> list[EodPrice]:
        stmt = (
            select(EodPrice)
            .where(EodPrice.trade_date == trade_date)
            .order_by(EodPrice.symbol.asc())
        )
        return list(self.session.scalars(stmt).all())


class PnlRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_daily_pnl(self, user_id: str, trade_date: str) -> DailyPnl | None:
        stmt = (
            select(DailyPnl)
            .where(DailyPnl.user_id == user_id, DailyPnl.trade_date == trade_date)
            .options(selectinload(DailyPnl.details))
        )
        return self.session.scalar(stmt)

    def latest_daily_pnl(
        self,
        user_id: str,
        *,
        before_trade_date: str | None = None,
        final_only: bool = False,
    ) -> DailyPnl | None:
        stmt = (
            select(DailyPnl)
            .where(DailyPnl.user_id == user_id)
            .options(selectinload(DailyPnl.details))
            .order_by(DailyPnl.trade_date.desc())
        )
        if before_trade_date:
            stmt = stmt.where(DailyPnl.trade_date <= before_trade_date)
        if final_only:
            stmt = stmt.where(DailyPnl.is_final.is_(True))
        return self.session.scalar(stmt)

    def previous_daily_pnl(self, user_id: str, trade_date: str) -> DailyPnl | None:
        stmt = (
            select(DailyPnl)
            .where(DailyPnl.user_id == user_id, DailyPnl.trade_date < trade_date)
            .options(selectinload(DailyPnl.details))
            .order_by(DailyPnl.trade_date.desc())
        )
        return self.session.scalar(stmt)

    def first_daily_pnl(self, user_id: str) -> DailyPnl | None:
        stmt = (
            select(DailyPnl)
            .where(DailyPnl.user_id == user_id)
            .order_by(DailyPnl.trade_date.asc())
        )
        return self.session.scalar(stmt)

    def list_calendar_rows(self, user_id: str, *, final_only: bool = True) -> list[DailyPnl]:
        stmt = (
            select(DailyPnl)
            .where(DailyPnl.user_id == user_id)
            .order_by(DailyPnl.trade_date.asc())
        )
        if final_only:
            stmt = stmt.where(DailyPnl.is_final.is_(True))
        return list(self.session.scalars(stmt).all())

    def list_detail_rows(self, user_id: str, trade_date: str) -> list[DailyPnlDetail]:
        daily = self.get_daily_pnl(user_id, trade_date)
        return sorted(daily.details, key=lambda row: row.symbol) if daily else []

    def list_non_final_trade_dates(
        self, user_id: str, before_trade_date: str | None = None
    ) -> list[str]:
        stmt = select(DailyPnl.trade_date).where(
            DailyPnl.user_id == user_id, DailyPnl.is_final.is_(False)
        )
        if before_trade_date:
            stmt = stmt.where(DailyPnl.trade_date < before_trade_date)
        stmt = stmt.order_by(DailyPnl.trade_date.asc())
        return list(self.session.scalars(stmt).all())

    def upsert_daily_pnl(
        self, *, user_id: str, trade_date: str, payload: dict, is_final: bool
    ) -> DailyPnl:
        row = self.get_daily_pnl(user_id, trade_date)
        if row:
            self.session.execute(
                delete(DailyPnlDetail).where(DailyPnlDetail.daily_pnl_id == row.id)
            )
            row.total_assets = payload["totalAssets"]
            row.available_cash = payload["availableCash"]
            row.position_market_value = payload["positionMarketValue"]
            row.daily_pnl = payload["dailyPnl"]
            row.daily_return = payload["dailyReturn"]
            row.cumulative_pnl = payload["cumulativePnl"]
            row.buy_amount = payload["buyAmount"]
            row.sell_amount = payload["sellAmount"]
            row.trade_count = payload["tradeCount"]
            row.is_final = is_final
            row.computed_at = market_now()
            self.session.flush()
        else:
            row = DailyPnl(
                id=new_id("pnl"),
                user_id=user_id,
                trade_date=trade_date,
                total_assets=payload["totalAssets"],
                available_cash=payload["availableCash"],
                position_market_value=payload["positionMarketValue"],
                daily_pnl=payload["dailyPnl"],
                daily_return=payload["dailyReturn"],
                cumulative_pnl=payload["cumulativePnl"],
                buy_amount=payload["buyAmount"],
                sell_amount=payload["sellAmount"],
                trade_count=payload["tradeCount"],
                is_final=is_final,
                computed_at=market_now(),
            )
            self.session.add(row)
            self.session.flush()

        for detail in payload["details"]:
            self.session.add(
                DailyPnlDetail(
                    id=new_id("pnld"),
                    daily_pnl_id=row.id,
                    trade_date=trade_date,
                    symbol=detail["symbol"],
                    symbol_name=detail["symbolName"],
                    opening_shares=detail["openingShares"],
                    closing_shares=detail["closingShares"],
                    buy_shares=detail["buyShares"],
                    sell_shares=detail["sellShares"],
                    buy_price=detail["buyPrice"],
                    sell_price=detail["sellPrice"],
                    open_price=detail["openPrice"],
                    close_price=detail["closePrice"],
                    daily_pnl=detail["dailyPnl"],
                    daily_return=detail["dailyReturn"],
                )
            )
        self.session.flush()
        self.session.refresh(row)
        return row
