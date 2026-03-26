import type { MarketStatus, PendingOrderRow } from "./types";

export function formatCurrency(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 2
  }).format(value);
}

export function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function statusLabel(status: MarketStatus) {
  switch (status) {
    case "pre_open":
      return "盘前";
    case "trading":
      return "交易中";
    case "lunch_break":
      return "午休";
    case "closed":
      return "已收盘";
    case "weekend":
      return "周末休市";
    case "holiday":
      return "节假日休市";
  }
}

export function orderStatusLabel(status: PendingOrderRow["status"] | "filled") {
  switch (status) {
    case "confirmed":
      return "已确认";
    case "pending":
      return "待触发";
    case "triggered":
      return "已触发";
    case "filled":
      return "已成交";
    case "cancelled":
      return "已撤单";
    case "expired":
      return "已失效";
    case "rejected":
      return "已拒绝";
  }
}
