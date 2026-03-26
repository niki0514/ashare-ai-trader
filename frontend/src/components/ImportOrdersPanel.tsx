import { useMemo } from "react";

import {
  matchesImportOrderFilter,
  orderValidityLabel,
  sortPendingOrdersByTradeDate,
  tradeSideLabel,
} from "../orderHelpers";
import type { PendingOrderRow } from "../types";
import { formatNumber, orderStatusLabel } from "../utils";

export type ImportOrderFilter =
  | "active"
  | "all"
  | "filled"
  | "cancelled"
  | "expired"
  | "rejected";

type ImportOrdersPanelProps = {
  pendingOrders: PendingOrderRow[];
  orderFilter: ImportOrderFilter;
  deletingOrderId: string | null;
  onOrderFilterChange: (value: ImportOrderFilter) => void;
  onDeleteOrder: (order: PendingOrderRow) => Promise<void> | void;
};

const IMPORT_ORDER_FILTER_OPTIONS: Array<{ value: ImportOrderFilter; label: string }> = [
  { value: "active", label: "进行中" },
  { value: "all", label: "全部" },
  { value: "filled", label: "已成交" },
  { value: "cancelled", label: "已撤单" },
  { value: "expired", label: "已失效" },
  { value: "rejected", label: "已拒绝" },
];

export function ImportOrdersPanel({
  pendingOrders,
  orderFilter,
  deletingOrderId,
  onOrderFilterChange,
  onDeleteOrder,
}: ImportOrdersPanelProps) {
  const importOrders = useMemo(
    () =>
      sortPendingOrdersByTradeDate(
        pendingOrders.filter((row) => matchesImportOrderFilter(row, orderFilter)),
      ),
    [orderFilter, pendingOrders],
  );

  return (
    <article className="input-card import-workflow-card">
      <div className="input-card-head import-toolbar-head">
        <div className="import-section-copy">
          <h3>委托记录</h3>
        </div>
        <div className="import-draft-meta">
          <span className="input-card-tag">显示 {importOrders.length} 条</span>
          <span className="input-card-tag">共 {pendingOrders.length} 条</span>
        </div>
      </div>
      <div className="history-toolbar import-orders-toolbar">
        <div className="history-filter-group">
          <span className="history-toolbar-label">状态筛选</span>
          <div className="history-mode-switch">
            {IMPORT_ORDER_FILTER_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={
                  orderFilter === option.value ? "history-mode-button active" : "history-mode-button"
                }
                onClick={() => onOrderFilterChange(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div className="history-toolbar-meta">
          <span>
            当前筛选:{" "}
            {IMPORT_ORDER_FILTER_OPTIONS.find((item) => item.value === orderFilter)?.label}
          </span>
        </div>
      </div>
      <div className="table-wrap history-table-wrap">
        <table className="history-table import-orders-table">
          <thead>
            <tr>
              <th>挂单时间</th>
              <th>股票代码</th>
              <th>名称</th>
              <th>方向</th>
              <th>挂单方式</th>
              <th className="align-right">委托价</th>
              <th className="align-right">手数</th>
              <th className="align-right">股数</th>
              <th>状态</th>
              <th>状态说明</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {importOrders.length > 0 ? (
              importOrders.map((row) => (
                <tr key={row.id}>
                  <td>{row.tradeDate}</td>
                  <td>{row.symbol}</td>
                  <td>{row.name}</td>
                  <td>
                    <span
                      className={
                        row.side === "BUY"
                          ? "trade-side-pill trade-side-buy"
                          : "trade-side-pill trade-side-sell"
                      }
                    >
                      {tradeSideLabel(row.side)}
                    </span>
                  </td>
                  <td>{orderValidityLabel(row.validity)}</td>
                  <td className="number-cell">{row.orderPrice.toFixed(2)}</td>
                  <td className="number-cell">{formatNumber(row.lots)}</td>
                  <td className="number-cell">{formatNumber(row.shares)}</td>
                  <td>
                    <span className={`status-pill status-${row.status}`}>
                      {orderStatusLabel(row.status)}
                    </span>
                  </td>
                  <td>{row.statusMessage || "-"}</td>
                  <td>
                    {row.canDelete ? (
                      <button
                        type="button"
                        className="order-delete-button"
                        onClick={() => void onDeleteOrder(row)}
                        disabled={deletingOrderId !== null}
                        title="撤回当前委托"
                      >
                        {deletingOrderId === row.id ? "撤单中..." : "撤单"}
                      </button>
                    ) : (
                      <span className="order-delete-placeholder">-</span>
                    )}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={11} className="empty-state">
                  暂无委托记录
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </article>
  );
}
