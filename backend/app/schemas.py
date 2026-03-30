from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


MarketStatus = Literal["pre_open", "trading", "lunch_break", "closed", "weekend", "holiday"]


class QuoteRow(BaseModel):
    symbol: str
    name: str
    price: float
    open: float
    previousClose: float
    high: float
    low: float
    updatedAt: str


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
    status: Literal["confirmed", "pending", "triggered", "filled", "cancelled", "expired", "rejected"]
    statusMessage: str
    updatedAt: str
    canDelete: bool = False
    detail: PendingOrderDetail


class PositionRow(BaseModel):
    symbol: str
    name: str
    shares: int
    sellableShares: int
    frozenSellShares: int
    costPrice: float
    lastPrice: float
    marketValue: float
    pnl: float
    returnRate: float
    todayPnl: float
    todayReturn: float


class PositionLotDetailRow(BaseModel):
    id: str
    openedDate: str
    openedAt: str
    originalShares: int
    remainingShares: int
    sellableShares: int
    frozenSellShares: int
    availableSellableShares: int
    costPrice: float
    costAmount: float
    marketValue: float


class PositionPendingSellOrderRow(BaseModel):
    id: str
    tradeDate: str
    orderPrice: float
    lots: int
    shares: int
    validity: Literal["DAY", "GTC"]
    status: Literal["confirmed", "pending", "triggered"]
    statusMessage: str
    createdAt: str
    updatedAt: str


class PositionsResponse(BaseModel):
    rows: list[PositionRow]


class PositionDetailResponse(BaseModel):
    tradeDate: str
    sellableTradeDate: str
    marketStatus: MarketStatus
    position: PositionRow
    lots: list[PositionLotDetailRow]
    pendingSellOrders: list[PositionPendingSellOrderRow]


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
    suggestedImportTradeDate: str
    marketStatus: MarketStatus
    updatedAt: str
    metrics: DashboardMetrics


class UserSummary(BaseModel):
    id: str
    name: str
    initialCash: float
    createdAt: str
    updatedAt: str


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    initialCash: float = Field(gt=0)


class ImportPreviewRow(BaseModel):
    rowNumber: int
    tradeDate: str
    symbol: str
    name: str
    side: Literal["BUY", "SELL"]
    price: float
    lots: int
    validity: Literal["DAY", "GTC"]
    validationStatus: Literal["VALID", "WARNING", "ERROR"]
    validationMessage: str


class ImportPreviewConfirmationItem(BaseModel):
    code: str
    summary: str
    rowNumbers: list[int]


class ImportPreviewConfirmation(BaseModel):
    required: bool
    token: str | None = None
    items: list[ImportPreviewConfirmationItem]


class ImportPreviewResponse(BaseModel):
    batchId: str
    targetTradeDate: str
    fileName: str | None = None
    sourceType: Literal["MANUAL", "XLSX", "CSV"] | None = None
    rows: list[ImportPreviewRow]
    confirmation: ImportPreviewConfirmation


class ImportUploadResponse(BaseModel):
    fileName: str | None = None
    sourceType: Literal["XLSX", "CSV"]
    batchIds: dict[str, str]
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


class ValidateOperationsRequest(BaseModel):
    targetTradeDate: str
    mode: Literal["DRAFT", "OVERWRITE", "APPEND"] = "APPEND"
    rows: list[ManualImportRowInput]


class ResolveSymbolsRequest(BaseModel):
    targetTradeDate: str
    symbols: list[str]


class ResolvedSymbolRow(BaseModel):
    symbol: str
    name: str
    resolved: bool
    referenceClose: float | None = None
    source: Literal["intraday", "eod", "quote", "unknown"]


class ResolveSymbolsResponse(BaseModel):
    rows: list[ResolvedSymbolRow]


class CommitImportsRequest(BaseModel):
    batchId: str
    mode: Literal["OVERWRITE", "APPEND", "DRAFT"] = "DRAFT"
    confirmWarnings: bool = False
    confirmationToken: str | None = None


class SubmitOperationsRequest(BaseModel):
    batchId: str
    mode: Literal["OVERWRITE", "APPEND"] = "APPEND"
    confirmWarnings: bool = False
    confirmationToken: str | None = None


class QuoteResponse(BaseModel):
    marketStatus: MarketStatus
    updatedAt: str
    stale: bool | None = None
    quotes: list[QuoteRow]


class ExecutionTickResult(BaseModel):
    processed: int
    updatedAt: datetime


class DeleteOrderResponse(BaseModel):
    deletedId: str
