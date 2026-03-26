import { useMemo } from "react";

import {
  isPendingOrderEffectiveToday,
  orderValidityLabel,
  sortPendingOrdersByTradeDate,
  tradeSideLabel,
} from "../orderHelpers";
import type { PendingOrderRow, PositionRow } from "../types";
import { formatCurrency, formatNumber, formatPercent, orderStatusLabel } from "../utils";
import { DataTable } from "./DataTable";

type PositionsTabProps = {
  rows: PositionRow[];
  pendingOrders: PendingOrderRow[];
  currentTradeDate: string;
  deletingOrderId: string | null;
  onDeleteOrder: (order: PendingOrderRow) => Promise<void> | void;
};

const POSITION_HEADERS = [
  "股票代码",
  "名称",
  "持仓数量",
  "可卖数量",
  "卖出冻结数量",
  "成本价",
  "现价",
  "市值",
  "今日盈亏",
  "今日盈亏比例",
  "累计盈亏",
  "累计收益率",
];

export function PositionsTab({
  rows,
  pendingOrders,
  currentTradeDate,
  deletingOrderId,
  onDeleteOrder,
}: PositionsTabProps) {
  const activePendingOrders = useMemo(
    () =>
      sortPendingOrdersByTradeDate(
        pendingOrders.filter((row) => isPendingOrderEffectiveToday(row, currentTradeDate)),
      ),
    [currentTradeDate, pendingOrders],
  );

  return (
    <section className="positions-layout">
      <DataTable
        headers={POSITION_HEADERS}
        rows={
          rows.length > 0
            ? rows.map((row) => (
                <tr key={row.symbol}>
                  <td>{row.symbol}</td>
                  <td>{row.name}</td>
                  <td>{formatNumber(row.shares)}</td>
                  <td>{formatNumber(row.sellableShares)}</td>
                  <td>{formatNumber(row.frozenSellShares)}</td>
                  <td>{row.costPrice.toFixed(3)}</td>
                  <td>{row.lastPrice.toFixed(2)}</td>
                  <td>{formatCurrency(row.marketValue)}</td>
                  <td className={row.todayPnl >= 0 ? "up" : "down"}>
                    {formatCurrency(row.todayPnl)}
                  </td>
                  <td className={row.todayReturn >= 0 ? "up" : "down"}>
                    {formatPercent(row.todayReturn)}
                  </td>
                  <td className={row.pnl >= 0 ? "up" : "down"}>{formatCurrency(row.pnl)}</td>
                  <td className={row.returnRate >= 0 ? "up" : "down"}>
                    {formatPercent(row.returnRate)}
                  </td>
                </tr>
              ))
            : [
                <tr key="empty-positions">
                  <td colSpan={12} className="empty-state">
                    当前无持仓
                  </td>
                </tr>,
              ]
        }
      />

      <div className="section-head compact">
        <h3>挂单明细</h3>
        <span>
          {activePendingOrders.length > 0
            ? `当前 ${formatNumber(activePendingOrders.length)} 条当日待执行委托`
            : "当前无当日待执行挂单"}
        </span>
      </div>
      <div className="pending-sections">
        {activePendingOrders.length > 0 ? (
          <article className="pending-orders-box">
            <table className="pending-orders-table">
              <thead>
                <tr>
                  <th>挂单日期</th>
                  <th>股票代码</th>
                  <th>操作</th>
                  <th>挂单方式</th>
                  <th>委托数量</th>
                  <th>委托价格</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {activePendingOrders.map((order) => (
                  <tr key={order.id}>
                    <td>{order.tradeDate}</td>
                    <td>{order.symbol}</td>
                    <td>{tradeSideLabel(order.side)}</td>
                    <td>{orderValidityLabel(order.validity)}</td>
                    <td>{formatNumber(order.shares)}</td>
                    <td>{order.orderPrice.toFixed(2)}</td>
                    <td>{orderStatusLabel(order.status)}</td>
                    <td>
                      <button
                        type="button"
                        className="order-delete-button"
                        onClick={() => void onDeleteOrder(order)}
                        disabled={deletingOrderId !== null || !order.canDelete}
                        title={order.canDelete ? "撤回当前委托" : "已成交委托不可撤单"}
                      >
                        {deletingOrderId === order.id ? "撤单中..." : "撤单"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </article>
        ) : (
          <div className="empty-panel">当前无待执行挂单</div>
        )}
      </div>
    </section>
  );
}
