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
    DailyPrice,
    ExecutionTrade,
    ImportBatch,
    ImportBatchItem,
    ImportBatchStatus,
    ImportMode,
    ImportSourceType,
    InstructionOrder,
    OrderEvent,
    OrderSide,
    OrderStatus,
    OrderValidity,
    PositionLot,
    PositionStatus,
    QuoteSnapshot,
    User,
    ValidationStatus,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


@dataclass(slots=True)
class SellAvailability:
    sellable_by_symbol: dict[str, int]
    reserved_by_symbol: dict[str, int]
    available_by_symbol: dict[str, int]


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_or_create(self, user_id: str, name: str, initial_cash: float) -> User:
        user = self.session.get(User, user_id)
        if user:
            return user
        user = User(id=user_id, name=name, initial_cash=initial_cash)
        self.session.add(user)
        self.session.flush()
        return user

    def list_ids(self) -> list[str]:
        return list(self.session.scalars(select(User.id).order_by(User.id)).all())


class OrderRepository:
    def __init__(self, session: Session):
        self.session = session

    def count_orders(self, user_id: str) -> int:
        return self.session.scalar(select(func.count()).select_from(InstructionOrder).where(InstructionOrder.user_id == user_id)) or 0

    def get_order(self, order_id: str) -> InstructionOrder | None:
        return self.session.get(InstructionOrder, order_id)

    def list_orders(self, user_id: str, statuses: Iterable[OrderStatus] | None = None) -> list[InstructionOrder]:
        stmt = select(InstructionOrder).where(InstructionOrder.user_id == user_id)
        if statuses:
            stmt = stmt.where(InstructionOrder.status.in_(list(statuses)))
        stmt = stmt.options(selectinload(InstructionOrder.events), selectinload(InstructionOrder.trades)).order_by(InstructionOrder.updated_at.desc())
        return list(self.session.scalars(stmt).unique().all())

    def list_pending_orders(self, user_id: str, trade_date: str) -> list[InstructionOrder]:
        stmt = (
            select(InstructionOrder)
            .where(
                InstructionOrder.user_id == user_id,
                or_(
                    and_(InstructionOrder.trade_date == trade_date, InstructionOrder.status.in_([OrderStatus.confirmed, OrderStatus.pending])),
                    and_(InstructionOrder.validity == OrderValidity.GTC, InstructionOrder.status.in_([OrderStatus.confirmed, OrderStatus.pending])),
                ),
            )
            .order_by(InstructionOrder.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def list_conflict_sell_orders(self, user_id: str, trade_date: str) -> list[InstructionOrder]:
        stmt = (
            select(InstructionOrder)
            .where(
                InstructionOrder.user_id == user_id,
                InstructionOrder.side == OrderSide.SELL,
                InstructionOrder.status.in_([OrderStatus.confirmed, OrderStatus.pending]),
                or_(InstructionOrder.trade_date == trade_date, InstructionOrder.validity == OrderValidity.GTC),
            )
            .order_by(InstructionOrder.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def list_day_orders_to_expire(self, user_id: str, trade_date: str) -> list[InstructionOrder]:
        stmt = select(InstructionOrder).where(
            InstructionOrder.user_id == user_id,
            InstructionOrder.trade_date == trade_date,
            InstructionOrder.validity == OrderValidity.DAY,
            InstructionOrder.status.in_([OrderStatus.confirmed, OrderStatus.pending, OrderStatus.triggered]),
        )
        return list(self.session.scalars(stmt).all())

    def list_confirmed_orders(self, user_id: str, trade_date: str) -> list[InstructionOrder]:
        stmt = select(InstructionOrder).where(
            InstructionOrder.user_id == user_id,
            InstructionOrder.status == OrderStatus.confirmed,
            or_(InstructionOrder.trade_date == trade_date, InstructionOrder.validity == OrderValidity.GTC),
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
        status_reason: str = "已导入待执行",
        created_at: datetime | None = None,
    ) -> InstructionOrder:
        now = created_at or datetime.now()
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

    def add_event(self, order_id: str, event_type: str, message: str, event_time: datetime | None = None) -> OrderEvent:
        event = OrderEvent(
            id=new_id("evt"),
            order_id=order_id,
            event_type=OrderStatus(event_type),
            event_time=event_time or datetime.now(),
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
        order.updated_at = datetime.now()
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

    def latest_import_batches(self, user_id: str, trade_date: str | None = None) -> list[ImportBatch]:
        stmt = select(ImportBatch).where(ImportBatch.user_id == user_id)
        if trade_date:
            stmt = stmt.where(ImportBatch.target_trade_date == trade_date)
        stmt = stmt.options(selectinload(ImportBatch.items)).order_by(ImportBatch.created_at.desc()).limit(5)
        return list(self.session.scalars(stmt).unique().all())

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
        stmt = select(ImportBatch).where(ImportBatch.id == batch_id).options(selectinload(ImportBatch.items))
        return self.session.scalar(stmt)

    def commit_import_batch(self, batch: ImportBatch, mode: str) -> int:
        if mode == ImportMode.OVERWRITE.value:
            self.session.execute(delete(InstructionOrder).where(InstructionOrder.user_id == batch.user_id, InstructionOrder.trade_date == batch.target_trade_date))
        imported_count = 0
        if mode != ImportMode.DRAFT.value:
            for item in batch.items:
                if item.validation_status == ValidationStatus.ERROR:
                    continue
                self.create_order(
                    user_id=batch.user_id,
                    trade_date=batch.target_trade_date,
                    symbol=item.symbol,
                    symbol_name=None,
                    side=item.side.value,
                    limit_price=item.limit_price,
                    lots=item.lots,
                    validity=item.validity.value,
                )
                imported_count += 1
        batch.status = ImportBatchStatus.VALIDATED if mode == ImportMode.DRAFT.value else ImportBatchStatus.COMMITTED
        batch.mode = ImportMode(mode)
        self.session.flush()
        return imported_count


class PortfolioRepository:
    def __init__(self, session: Session):
        self.session = session

    def latest_cash(self, user_id: str, before: datetime | None = None) -> CashLedger | None:
        stmt = select(CashLedger).where(CashLedger.user_id == user_id)
        if before is not None:
            stmt = stmt.where(CashLedger.entry_time <= before)
        stmt = stmt.order_by(CashLedger.entry_time.desc())
        return self.session.scalar(stmt)

    def add_cash_entry(
        self,
        *,
        user_id: str,
        entry_time: datetime,
        entry_type: str,
        amount: float,
        balance_after: float,
        reference_id: str | None = None,
        reference_type: str | None = None,
    ) -> CashLedger:
        row = CashLedger(
            id=new_id("cash"),
            user_id=user_id,
            entry_time=entry_time,
            entry_type=CashEntryType(entry_type),
            amount=amount,
            balance_after=balance_after,
            reference_id=reference_id,
            reference_type=reference_type,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def open_lots(self, user_id: str, symbol: str | None = None) -> list[PositionLot]:
        stmt = select(PositionLot).where(PositionLot.user_id == user_id, PositionLot.status == PositionStatus.OPEN)
        if symbol:
            stmt = stmt.where(PositionLot.symbol == symbol)
        stmt = stmt.order_by(PositionLot.opened_at.asc())
        return list(self.session.scalars(stmt).all())

    def all_lots(self, user_id: str) -> list[PositionLot]:
        stmt = select(PositionLot).where(PositionLot.user_id == user_id).order_by(PositionLot.opened_at.asc())
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

    def update_lot(self, lot: PositionLot, *, remaining_shares: int, sellable_shares: int, closed_at: datetime | None = None) -> None:
        lot.remaining_shares = remaining_shares
        lot.sellable_shares = sellable_shares
        lot.status = PositionStatus.CLOSED if remaining_shares == 0 else PositionStatus.OPEN
        lot.closed_at = closed_at if remaining_shares == 0 else None
        self.session.flush()

    def unlock_previous_lots(self, user_id: str, trade_date: str) -> None:
        stmt = select(PositionLot).where(PositionLot.user_id == user_id, PositionLot.status == PositionStatus.OPEN, PositionLot.opened_date < trade_date)
        for row in self.session.scalars(stmt).all():
            row.sellable_shares = row.remaining_shares
        self.session.flush()

    def get_pending_sell_orders_by_symbol(self, user_id: str) -> dict[str, list[InstructionOrder]]:
        stmt = select(InstructionOrder).where(
            InstructionOrder.user_id == user_id,
            InstructionOrder.side == OrderSide.SELL,
            InstructionOrder.status.in_([OrderStatus.confirmed, OrderStatus.pending, OrderStatus.triggered]),
        ).order_by(InstructionOrder.created_at.asc())
        grouped: dict[str, list[InstructionOrder]] = defaultdict(list)
        for row in self.session.scalars(stmt).all():
            grouped[row.symbol].append(row)
        return grouped

    def get_available_sellable_shares(self, user_id: str, exclude_order_id: str | None = None) -> SellAvailability:
        sellable_by_symbol: dict[str, int] = defaultdict(int)
        for lot in self.open_lots(user_id):
            sellable_by_symbol[lot.symbol] += lot.sellable_shares

        reserved_stmt = select(InstructionOrder.symbol, InstructionOrder.shares).where(
            InstructionOrder.user_id == user_id,
            InstructionOrder.side == OrderSide.SELL,
            InstructionOrder.status.in_([OrderStatus.confirmed, OrderStatus.pending, OrderStatus.triggered]),
        )
        if exclude_order_id:
            reserved_stmt = reserved_stmt.where(InstructionOrder.id != exclude_order_id)
        reserved_by_symbol: dict[str, int] = defaultdict(int)
        for symbol, shares in self.session.execute(reserved_stmt).all():
            reserved_by_symbol[symbol] += shares

        available_by_symbol = {symbol: max(0, sellable_by_symbol.get(symbol, 0) - reserved_by_symbol.get(symbol, 0)) for symbol in sellable_by_symbol}
        return SellAvailability(dict(sellable_by_symbol), dict(reserved_by_symbol), available_by_symbol)


class MarketDataRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_daily_price(self, symbol: str, trade_date: str) -> DailyPrice | None:
        stmt = select(DailyPrice).where(DailyPrice.symbol == symbol, DailyPrice.trade_date == trade_date)
        return self.session.scalar(stmt)

    def upsert_quote_snapshot(self, row: dict) -> QuoteSnapshot:
        stmt = select(QuoteSnapshot).where(QuoteSnapshot.symbol == row["symbol"])
        existing = self.session.scalar(stmt)
        if existing:
            existing.symbol_name = row["name"]
            existing.price = row["price"]
            existing.open_price = row["open"]
            existing.previous_close = row["previousClose"]
            existing.high_price = row["high"]
            existing.low_price = row["low"]
            existing.updated_at = row["updated_at"]
            existing.source = row.get("source")
            self.session.flush()
            return existing
        snapshot = QuoteSnapshot(
            id=new_id("quote"),
            symbol=row["symbol"],
            symbol_name=row["name"],
            price=row["price"],
            open_price=row["open"],
            previous_close=row["previousClose"],
            high_price=row["high"],
            low_price=row["low"],
            updated_at=row["updated_at"],
            source=row.get("source"),
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def list_quotes(self, symbols: list[str] | None = None) -> list[QuoteSnapshot]:
        stmt = select(QuoteSnapshot)
        if symbols:
            stmt = stmt.where(QuoteSnapshot.symbol.in_(symbols))
        stmt = stmt.order_by(QuoteSnapshot.symbol.asc())
        return list(self.session.scalars(stmt).all())

    def get_quote(self, symbol: str) -> QuoteSnapshot | None:
        return self.session.scalar(select(QuoteSnapshot).where(QuoteSnapshot.symbol == symbol))

    def latest_quote_updated_at(self) -> datetime | None:
        return self.session.scalar(select(func.max(QuoteSnapshot.updated_at)))

    def upsert_daily_price(self, *, symbol: str, symbol_name: str | None, trade_date: str, close_price: float, open_price: float = 0, previous_close: float = 0, high_price: float = 0, low_price: float = 0, is_final: bool = True, source: str | None = None) -> DailyPrice:
        stmt = select(DailyPrice).where(DailyPrice.symbol == symbol, DailyPrice.trade_date == trade_date)
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
            existing.updated_at = datetime.now()
            self.session.flush()
            return existing
        row = DailyPrice(
            id=new_id("dpx"),
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
        )
        self.session.add(row)
        self.session.flush()
        return row

    def latest_daily_price(self, symbol: str, trade_date_lte: str | None = None) -> DailyPrice | None:
        stmt = select(DailyPrice).where(DailyPrice.symbol == symbol)
        if trade_date_lte:
            stmt = stmt.where(DailyPrice.trade_date <= trade_date_lte)
        stmt = stmt.order_by(DailyPrice.trade_date.desc())
        return self.session.scalar(stmt)

    def previous_daily_price(self, symbol: str, trade_date: str) -> DailyPrice | None:
        stmt = (
            select(DailyPrice)
            .where(DailyPrice.symbol == symbol, DailyPrice.trade_date < trade_date)
            .order_by(DailyPrice.trade_date.desc())
        )
        return self.session.scalar(stmt)

    def list_daily_prices(self, trade_date: str) -> list[DailyPrice]:
        stmt = select(DailyPrice).where(DailyPrice.trade_date == trade_date).order_by(DailyPrice.symbol.asc())
        return list(self.session.scalars(stmt).all())


class PnlRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_daily_pnl(self, user_id: str, trade_date: str) -> DailyPnl | None:
        stmt = select(DailyPnl).where(DailyPnl.user_id == user_id, DailyPnl.trade_date == trade_date).options(selectinload(DailyPnl.details))
        return self.session.scalar(stmt)

    def latest_daily_pnl(self, user_id: str) -> DailyPnl | None:
        stmt = select(DailyPnl).where(DailyPnl.user_id == user_id).options(selectinload(DailyPnl.details)).order_by(DailyPnl.trade_date.desc())
        return self.session.scalar(stmt)

    def previous_daily_pnl(self, user_id: str, trade_date: str) -> DailyPnl | None:
        stmt = select(DailyPnl).where(DailyPnl.user_id == user_id, DailyPnl.trade_date < trade_date).options(selectinload(DailyPnl.details)).order_by(DailyPnl.trade_date.desc())
        return self.session.scalar(stmt)

    def first_daily_pnl(self, user_id: str) -> DailyPnl | None:
        stmt = select(DailyPnl).where(DailyPnl.user_id == user_id).order_by(DailyPnl.trade_date.asc())
        return self.session.scalar(stmt)

    def list_calendar_rows(self, user_id: str) -> list[DailyPnl]:
        stmt = select(DailyPnl).where(DailyPnl.user_id == user_id).order_by(DailyPnl.trade_date.asc())
        return list(self.session.scalars(stmt).all())

    def list_detail_rows(self, user_id: str, trade_date: str) -> list[DailyPnlDetail]:
        daily = self.get_daily_pnl(user_id, trade_date)
        return sorted(daily.details, key=lambda row: row.symbol) if daily else []

    def upsert_daily_pnl(self, *, user_id: str, trade_date: str, payload: dict, is_final: bool) -> DailyPnl:
        row = self.get_daily_pnl(user_id, trade_date)
        if row:
            for detail in list(row.details):
                self.session.delete(detail)
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
            row.computed_at = datetime.now()
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
                computed_at=datetime.now(),
            )
            self.session.add(row)
            self.session.flush()

        for detail in payload["details"]:
            self.session.add(DailyPnlDetail(
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
                realized_pnl=detail["realizedPnl"],
                unrealized_pnl=detail["unrealizedPnl"],
                daily_pnl=detail["dailyPnl"],
                daily_return=detail["dailyReturn"],
            ))
        self.session.flush()
        self.session.refresh(row)
        return row
