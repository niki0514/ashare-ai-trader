import type { ClosedPositionRow } from "../types";
import { formatCurrency, formatNumber, formatPercent } from "../utils";
import { DataTable } from "./DataTable";

type ClosedPositionsTabProps = {
  rows: ClosedPositionRow[];
};

const CLOSED_POSITION_HEADERS = [
  "股票代码",
  "名称",
  "建仓时间",
  "清仓时间",
  "累计买入数量",
  "累计卖出数量",
  "买入均价",
  "卖出均价",
  "已实现盈亏",
  "收益率",
];

export function ClosedPositionsTab({ rows }: ClosedPositionsTabProps) {
  return (
    <section className="positions-layout">
      <div className="section-head">
        <h3>已清仓</h3>
        <span>
          {rows.length > 0
            ? `当前累计 ${formatNumber(rows.length)} 次已完成清仓`
            : "当前无已清仓记录"}
        </span>
      </div>

      <DataTable
        headers={CLOSED_POSITION_HEADERS}
        rows={
          rows.length > 0
            ? rows.map((row) => (
                <tr key={`${row.symbol}-${row.openedAt}-${row.closedAt}`}>
                  <td>{row.symbol}</td>
                  <td>{row.name}</td>
                  <td>{row.openedAt}</td>
                  <td>{row.closedAt}</td>
                  <td>{formatNumber(row.buyShares)}</td>
                  <td>{formatNumber(row.sellShares)}</td>
                  <td>{row.buyPrice.toFixed(3)}</td>
                  <td>{row.sellPrice.toFixed(3)}</td>
                  <td className={row.realizedPnl >= 0 ? "up" : "down"}>
                    {formatCurrency(row.realizedPnl)}
                  </td>
                  <td className={row.returnRate >= 0 ? "up" : "down"}>
                    {formatPercent(row.returnRate)}
                  </td>
                </tr>
              ))
            : [
                <tr key="empty-closed-positions">
                  <td colSpan={10} className="empty-state">
                    当前无已清仓记录
                  </td>
                </tr>,
              ]
        }
      />
    </section>
  );
}
