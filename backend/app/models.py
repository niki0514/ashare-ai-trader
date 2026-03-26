from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .time_utils import market_now


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderValidity(str, enum.Enum):
    DAY = "DAY"
    GTC = "GTC"


class OrderStatus(str, enum.Enum):
    confirmed = "confirmed"
    pending = "pending"
    triggered = "triggered"
    filled = "filled"
    cancelled = "cancelled"
    expired = "expired"
    rejected = "rejected"


class PositionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CashEntryType(str, enum.Enum):
    INITIAL = "INITIAL"
    BUY = "BUY"
    SELL = "SELL"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class ImportSourceType(str, enum.Enum):
    MANUAL = "MANUAL"
    XLSX = "XLSX"
    CSV = "CSV"


class ImportMode(str, enum.Enum):
    DRAFT = "DRAFT"
    OVERWRITE = "OVERWRITE"
    APPEND = "APPEND"


class ImportBatchStatus(str, enum.Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


class ValidationStatus(str, enum.Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    ERROR = "ERROR"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    initial_cash: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=market_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=market_now, onupdate=market_now)


class InstructionOrder(Base):
    __tablename__ = "instruction_orders"
    __table_args__ = (
        Index("ix_instruction_orders_user_trade_status", "user_id", "trade_date", "status"),
        Index("ix_instruction_orders_user_symbol_trade", "user_id", "symbol", "trade_date"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    trade_date: Mapped[str] = mapped_column(String(10))
    symbol: Mapped[str] = mapped_column(String(16))
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide))
    limit_price: Mapped[float] = mapped_column(Float)
    lots: Mapped[int] = mapped_column(Integer)
    shares: Mapped[int] = mapped_column(Integer)
    validity: Mapped[OrderValidity] = mapped_column(Enum(OrderValidity))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.confirmed)
    status_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=market_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=market_now, onupdate=market_now)

    events: Mapped[list[OrderEvent]] = relationship(back_populates="order", cascade="all, delete-orphan")
    trades: Mapped[list[ExecutionTrade]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (Index("ix_order_events_order_time", "order_id", "event_time"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("instruction_orders.id", ondelete="CASCADE"))
    event_type: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus))
    event_time: Mapped[datetime] = mapped_column(DateTime, default=market_now)
    message: Mapped[str] = mapped_column(String(255))
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    order: Mapped[InstructionOrder] = relationship(back_populates="events")


class ExecutionTrade(Base):
    __tablename__ = "execution_trades"
    __table_args__ = (Index("ix_execution_trades_user_symbol_fill", "user_id", "symbol", "fill_time"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    order_id: Mapped[str] = mapped_column(ForeignKey("instruction_orders.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide))
    order_price: Mapped[float] = mapped_column(Float)
    fill_price: Mapped[float] = mapped_column(Float)
    cost_basis_amount: Mapped[float] = mapped_column(Float, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    lots: Mapped[int] = mapped_column(Integer)
    shares: Mapped[int] = mapped_column(Integer)
    fill_time: Mapped[datetime] = mapped_column(DateTime)
    cash_after: Mapped[float] = mapped_column(Float)
    position_after: Mapped[int] = mapped_column(Integer)

    order: Mapped[InstructionOrder] = relationship(back_populates="trades")


class PositionLot(Base):
    __tablename__ = "position_lots"
    __table_args__ = (Index("ix_position_lots_user_symbol_status", "user_id", "symbol", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(16))
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opened_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_trade_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_date: Mapped[str] = mapped_column(String(10))
    opened_at: Mapped[datetime] = mapped_column(DateTime)
    cost_price: Mapped[float] = mapped_column(Float)
    original_shares: Mapped[int] = mapped_column(Integer)
    remaining_shares: Mapped[int] = mapped_column(Integer)
    sellable_shares: Mapped[int] = mapped_column(Integer)
    status: Mapped[PositionStatus] = mapped_column(Enum(PositionStatus), default=PositionStatus.OPEN)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CashLedger(Base):
    __tablename__ = "cash_ledger"
    __table_args__ = (Index("ix_cash_ledger_user_time", "user_id", "entry_time"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    entry_time: Mapped[datetime] = mapped_column(DateTime, default=market_now)
    entry_type: Mapped[CashEntryType] = mapped_column(Enum(CashEntryType))
    amount: Mapped[float] = mapped_column(Float)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DailyPnl(Base):
    __tablename__ = "daily_pnl"
    __table_args__ = (
        UniqueConstraint("user_id", "trade_date", name="uq_daily_pnl_user_trade_date"),
        Index("ix_daily_pnl_user_trade_date", "user_id", "trade_date"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    trade_date: Mapped[str] = mapped_column(String(10))
    total_assets: Mapped[float] = mapped_column(Float)
    available_cash: Mapped[float] = mapped_column(Float)
    position_market_value: Mapped[float] = mapped_column(Float)
    daily_pnl: Mapped[float] = mapped_column(Float)
    daily_return: Mapped[float] = mapped_column(Float)
    cumulative_pnl: Mapped[float] = mapped_column(Float)
    buy_amount: Mapped[float] = mapped_column(Float)
    sell_amount: Mapped[float] = mapped_column(Float)
    trade_count: Mapped[int] = mapped_column(Integer)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=market_now)

    details: Mapped[list[DailyPnlDetail]] = relationship(back_populates="daily", cascade="all, delete-orphan")


class DailyPnlDetail(Base):
    __tablename__ = "daily_pnl_details"
    __table_args__ = (Index("ix_daily_pnl_details_trade_symbol", "trade_date", "symbol"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    daily_pnl_id: Mapped[str] = mapped_column(ForeignKey("daily_pnl.id", ondelete="CASCADE"))
    trade_date: Mapped[str] = mapped_column(String(10))
    symbol: Mapped[str] = mapped_column(String(16))
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opening_shares: Mapped[int] = mapped_column(Integer, default=0)
    closing_shares: Mapped[int] = mapped_column(Integer)
    buy_shares: Mapped[int] = mapped_column(Integer, default=0)
    sell_shares: Mapped[int] = mapped_column(Integer, default=0)
    buy_price: Mapped[float] = mapped_column(Float, default=0)
    sell_price: Mapped[float] = mapped_column(Float, default=0)
    open_price: Mapped[float] = mapped_column(Float, default=0)
    close_price: Mapped[float] = mapped_column(Float)
    daily_pnl: Mapped[float] = mapped_column(Float)
    daily_return: Mapped[float] = mapped_column(Float)

    daily: Mapped[DailyPnl] = relationship(back_populates="details")


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (Index("ix_import_batches_user_trade_status", "user_id", "target_trade_date", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    target_trade_date: Mapped[str] = mapped_column(String(10))
    source_type: Mapped[ImportSourceType] = mapped_column(Enum(ImportSourceType))
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mode: Mapped[ImportMode] = mapped_column(Enum(ImportMode))
    status: Mapped[ImportBatchStatus] = mapped_column(Enum(ImportBatchStatus), default=ImportBatchStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=market_now)

    items: Mapped[list[ImportBatchItem]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class ImportBatchItem(Base):
    __tablename__ = "import_batch_items"
    __table_args__ = (Index("ix_import_batch_items_batch_row", "batch_id", "row_number"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    row_number: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(16))
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide))
    limit_price: Mapped[float] = mapped_column(Float)
    lots: Mapped[int] = mapped_column(Integer)
    validity: Mapped[OrderValidity] = mapped_column(Enum(OrderValidity))
    validation_status: Mapped[ValidationStatus] = mapped_column(Enum(ValidationStatus))
    validation_message: Mapped[str | None] = mapped_column(String(255), nullable=True)

    batch: Mapped[ImportBatch] = relationship(back_populates="items")


class IntradayQuote(Base):
    __tablename__ = "intraday_quotes"
    __table_args__ = (
        UniqueConstraint("symbol", "quoted_at", name="uq_intraday_quotes_symbol_quoted_at"),
        Index("ix_intraday_quotes_trade_symbol_time", "trade_date", "symbol", "quoted_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trade_date: Mapped[str] = mapped_column(String(10))
    quoted_at: Mapped[datetime] = mapped_column(DateTime)
    price: Mapped[float] = mapped_column(Float)
    open_price: Mapped[float] = mapped_column(Float, default=0)
    previous_close: Mapped[float] = mapped_column(Float, default=0)
    high_price: Mapped[float] = mapped_column(Float, default=0)
    low_price: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=market_now, onupdate=market_now)


class EodPrice(Base):
    __tablename__ = "eod_prices"
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", name="uq_eod_prices_symbol_trade_date"),
        Index("ix_eod_prices_trade_symbol", "trade_date", "symbol"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trade_date: Mapped[str] = mapped_column(String(10))
    close_price: Mapped[float] = mapped_column(Float)
    open_price: Mapped[float] = mapped_column(Float, default=0)
    previous_close: Mapped[float] = mapped_column(Float, default=0)
    high_price: Mapped[float] = mapped_column(Float, default=0)
    low_price: Mapped[float] = mapped_column(Float, default=0)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=market_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=market_now, onupdate=market_now)
