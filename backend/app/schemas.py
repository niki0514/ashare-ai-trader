from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


MarketStatus = Literal["pre_open", "trading", "lunch_break", "closed", "weekend"]


class QuoteRow(BaseModel):
    symbol: str
    name: str
    price: float
    open: float
    previousClose: float
    high: float
    low: float
    updatedAt: str


class PositionPendingOrder(BaseModel):
    id: str
    tradeDate: str
    side: Literal["BUY", "SELL"]
    price: float
    shares: int
    lots: int
    status: Literal["confirmed", "pending", "triggered"]


class PositionRow(BaseModel):
    symbol: str
    name: str
    shares: int
    sellableShares: int
    frozenSellShares: int
    costPrice: float
    lastPrice: float
    todayPnl: float
    todayReturn: float
    marketValue: float
    pnl: float
    returnRate: float
    pendingOrders: list[PositionPendingOrder]


class PendingOrderTransition(BaseModel):
    at: str
    status: str
    message: str


class PendingOrderDetail(BaseModel):
    orderText: str
    transitions: list[PendingOrderTransition]
    fillPrice: float | None = None
    fillTime: str | None = None


class PendingOrderRow(BaseModel):
    id: str
    tradeDate: str
    symbol: str
    name: str
    side: Literal["BUY", "SELL"]
    orderPrice: float
    lots: int
    shares: int
    validity: Literal["DAY", "GTC"]
    status: Literal["confirmed", "pending", "triggered", "filled", "expired", "rejected"]
    statusMessage: str
    updatedAt: str
    detail: PendingOrderDetail


class HistoryRow(BaseModel):
    id: str
    time: str
    fillTime: str
    symbol: str
    name: str
    side: Literal["BUY", "SELL"]
    orderPrice: float
    fillPrice: float | None = None
    lots: int
    shares: int


class CalendarDay(BaseModel):
    date: str
    dailyPnl: float
    dailyReturn: float
    tradeCount: int


class DailyPnlDetailRow(BaseModel):
    symbol: str
    name: str
    openingShares: int
    closingShares: int
    buyShares: int
    sellShares: int
    buyPrice: float
    sellPrice: float
    openPrice: float
    closePrice: float
    realizedPnl: float
    unrealizedPnl: float
    dailyPnl: float
    dailyReturn: float


class DashboardMetrics(BaseModel):
    totalAssets: float
    availableCash: float
    positionMarketValue: float
    dailyPnl: float
    cumulativePnl: float
    exposureRatio: float


class DashboardResponse(BaseModel):
    tradeDate: str
    marketStatus: MarketStatus
    updatedAt: str
    metrics: DashboardMetrics


class ImportPreviewRow(BaseModel):
    rowNumber: int
    symbol: str
    side: Literal["BUY", "SELL"]
    price: float
    lots: int
    validity: Literal["DAY", "GTC"]
    validationStatus: Literal["VALID", "WARNING", "ERROR"]
    validationMessage: str


class ImportPreviewResponse(BaseModel):
    batchId: str
    targetTradeDate: str
    fileName: str | None = None
    sourceType: Literal["MANUAL", "XLSX", "CSV"] | None = None
    rows: list[ImportPreviewRow]


class ImportCommitResponse(BaseModel):
    batchId: str
    targetTradeDate: str
    mode: Literal["OVERWRITE", "APPEND", "DRAFT"]
    importedCount: int


class ManualImportRowInput(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    price: float = Field(gt=0)
    lots: int = Field(gt=0)
    validity: Literal["DAY", "GTC"]


class PreviewImportsRequest(BaseModel):
    targetTradeDate: str
    mode: Literal["DRAFT", "OVERWRITE", "APPEND"] = "DRAFT"
    sourceType: Literal["MANUAL", "XLSX", "CSV"] = "MANUAL"
    fileName: str | None = None
    rows: list[ManualImportRowInput]


class CommitImportsRequest(BaseModel):
    batchId: str
    mode: Literal["OVERWRITE", "APPEND", "DRAFT"] = "DRAFT"


class QuoteResponse(BaseModel):
    marketStatus: MarketStatus
    updatedAt: str
    stale: bool | None = None
    quotes: list[QuoteRow]


class ExecutionTickResult(BaseModel):
    processed: int
    updatedAt: datetime
