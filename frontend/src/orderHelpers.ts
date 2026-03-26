import type { ManualImportRowInput } from "./api";
import type { MarketStatus, PendingOrderRow } from "./types";


const NON_TRADING_MARKET_STATUSES: MarketStatus[] = ["closed", "weekend", "holiday"];
const IMPORT_BLOCKED_MARKET_STATUSES: MarketStatus[] = ["trading"];


export function tradeSideLabel(side: "BUY" | "SELL") {
  return side === "BUY" ? "买入" : "卖出";
}


export function orderValidityLabel(validity: ManualImportRowInput["validity"]) {
  return validity === "GTC" ? "持续挂单" : "当日挂单";
}


export function isNonTradingMarketStatus(status: MarketStatus | null | undefined) {
  return status !== null && status !== undefined && NON_TRADING_MARKET_STATUSES.includes(status);
}


export function isImportBlockedMarketStatus(status: MarketStatus | null | undefined) {
  return (
    status !== null &&
    status !== undefined &&
    IMPORT_BLOCKED_MARKET_STATUSES.includes(status)
  );
}


export function isActivePendingOrderStatus(status: PendingOrderRow["status"]) {
  return status === "confirmed" || status === "pending" || status === "triggered";
}


export function isPendingOrderEffectiveToday(order: PendingOrderRow, currentTradeDate: string) {
  if (!isActivePendingOrderStatus(order.status)) {
    return false;
  }

  if (order.tradeDate === currentTradeDate) {
    return true;
  }

  return order.validity === "GTC" && order.tradeDate < currentTradeDate;
}


export function matchesImportOrderFilter(
  order: PendingOrderRow,
  filter: "active" | "all" | "filled" | "cancelled" | "expired" | "rejected",
) {
  if (filter === "all") {
    return true;
  }

  if (filter === "active") {
    return isActivePendingOrderStatus(order.status);
  }

  return order.status === filter;
}


export function sortPendingOrdersByTradeDate(rows: PendingOrderRow[]) {
  return [...rows].sort(
    (a, b) => b.tradeDate.localeCompare(a.tradeDate) || b.updatedAt.localeCompare(a.updatedAt),
  );
}
