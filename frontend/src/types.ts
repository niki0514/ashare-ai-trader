export type MarketStatus = "pre_open" | "trading" | "lunch_break" | "closed" | "weekend";

export type DashboardResponse = {
  tradeDate: string;
  suggestedImportTradeDate: string;
  marketStatus: MarketStatus;
  updatedAt: string;
  metrics: {
    totalAssets: number;
    availableCash: number;
    positionMarketValue: number;
    dailyPnl: number;
    cumulativePnl: number;
    exposureRatio: number;
  };
};

export type UserSummary = {
  id: string;
  name: string;
  initialCash: number;
  createdAt: string;
  updatedAt: string;
};

export type PositionRow = {
  symbol: string;
  name: string;
  shares: number;
  sellableShares: number;
  frozenSellShares: number;
  costPrice: number;
  lastPrice: number;
  marketValue: number;
  pnl: number;
  returnRate: number;
  todayPnl: number;
  todayReturn: number;
  pendingOrders: Array<{
    id: string;
    tradeDate: string;
    side: "BUY" | "SELL";
    price: number;
    shares: number;
    lots: number;
    status: "confirmed" | "pending" | "triggered";
  }>;
};

export type PendingOrderRow = {
  id: string;
  tradeDate: string;
  symbol: string;
  name: string;
  side: "BUY" | "SELL";
  orderPrice: number;
  lots: number;
  shares: number;
  validity: "DAY" | "GTC";
  status: "confirmed" | "pending" | "triggered" | "filled" | "cancelled" | "expired" | "rejected";
  statusMessage: string;
  updatedAt: string;
  canDelete: boolean;
  detail: {
    orderText: string;
    transitions: Array<{ at: string; status: string; message: string }>;
    fillPrice?: number;
    fillTime?: string;
  };
};

export type HistoryRow = {
  id: string;
  time: string;
  fillTime: string;
  symbol: string;
  name: string;
  side: "BUY" | "SELL";
  orderPrice: number;
  fillPrice?: number;
  lots: number;
  shares: number;
};

export type CalendarDay = {
  date: string;
  dailyPnl: number;
  dailyReturn: number;
  tradeCount: number;
};

export type DailyPnlDetailRow = {
  symbol: string;
  name: string;
  openingShares: number;
  closingShares: number;
  buyShares: number;
  sellShares: number;
  buyPrice: number;
  sellPrice: number;
  openPrice: number;
  closePrice: number;
  realizedPnl: number;
  unrealizedPnl: number;
  dailyPnl: number;
  dailyReturn: number;
};

export type QuoteRow = {
  symbol: string;
  name: string;
  price: number;
  open: number;
  previousClose: number;
  high: number;
  low: number;
  updatedAt: string;
};

export type QuoteResponse = {
  marketStatus: MarketStatus;
  updatedAt: string;
  quotes: QuoteRow[];
};

export type ImportPreviewRow = {
  rowNumber: number;
  tradeDate: string;
  symbol: string;
  side: "BUY" | "SELL";
  price: number;
  lots: number;
  validity: "DAY" | "GTC";
  validationStatus: "VALID" | "WARNING" | "ERROR";
  validationMessage: string;
};

export type ImportPreviewResponse = {
  batchId: string;
  targetTradeDate: string;
  fileName?: string;
  sourceType?: "MANUAL" | "XLSX" | "CSV";
  rows: ImportPreviewRow[];
};

export type ImportUploadResponse = {
  fileName?: string;
  sourceType: "XLSX" | "CSV";
  batchIds: Record<string, string>;
  rows: ImportPreviewRow[];
};

export type ImportCommitResponse = {
  batchId: string;
  targetTradeDate: string;
  mode: "OVERWRITE" | "APPEND" | "DRAFT";
  importedCount: number;
};

export type LatestImportBatchItem = {
  rowNumber: number;
  symbol: string;
  side: "BUY" | "SELL";
  limitPrice: number;
  lots: number;
  validity: "DAY" | "GTC";
  validationStatus: "VALID" | "WARNING" | "ERROR";
  validationMessage?: string;
};

export type LatestImportBatch = {
  id: string;
  targetTradeDate: string;
  sourceType: "MANUAL" | "XLSX" | "CSV";
  fileName?: string;
  mode: "OVERWRITE" | "APPEND" | "DRAFT";
  status: "PENDING" | "VALIDATED" | "COMMITTED" | "FAILED";
  createdAt: string;
  items: LatestImportBatchItem[];
};
