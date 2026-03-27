import { useEffect, useMemo, useState } from "react";

import type { CalendarDay, DailyPnlDetailRow, HistoryRow } from "../types";
import { formatCurrency, formatNumber, formatPercent } from "../utils";

type PnlTabProps = {
  rows: CalendarDay[];
  selectedDate: string;
  onSelectDate: (date: string) => void;
  details: DailyPnlDetailRow[];
  trades: HistoryRow[];
};

const WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"];

function monthKeyFromDate(value: string) {
  return value.slice(0, 7);
}

function monthLabel(monthKey: string) {
  const [year, month] = monthKey.split("-").map(Number);
  return `${year}年${month}月`;
}

function shiftMonthKey(monthKey: string, offset: number) {
  const [year, month] = monthKey.split("-").map(Number);
  return `${new Date(year, month - 1 + offset, 1).getFullYear()}-${String(
    new Date(year, month - 1 + offset, 1).getMonth() + 1,
  ).padStart(2, "0")}`;
}

function buildMonthCells(monthKey: string, rowsByDate: Map<string, CalendarDay>) {
  const [year, month] = monthKey.split("-").map(Number);
  const firstDay = new Date(year, month - 1, 1);
  const firstWeekday = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month, 0).getDate();
  const totalCells = Math.ceil((firstWeekday + daysInMonth) / 7) * 7;

  return Array.from({ length: totalCells }, (_, index) => {
    const dayNumber = index - firstWeekday + 1;

    if (dayNumber < 1 || dayNumber > daysInMonth) {
      return null;
    }

    const date = `${monthKey}-${String(dayNumber).padStart(2, "0")}`;
    return {
      date,
      dayNumber,
      data: rowsByDate.get(date) ?? null,
    };
  });
}

export function PnlTab({
  rows,
  selectedDate,
  onSelectDate,
  details,
  trades,
}: PnlTabProps) {
  const rowsByDate = useMemo(() => new Map(rows.map((row) => [row.date, row])), [rows]);
  const availableMonths = useMemo(
    () => Array.from(new Set(rows.map((row) => monthKeyFromDate(row.date)))).sort(),
    [rows],
  );
  const [visibleMonth, setVisibleMonth] = useState(() => monthKeyFromDate(selectedDate));

  useEffect(() => {
    const selectedMonth = monthKeyFromDate(selectedDate);

    if (selectedMonth !== visibleMonth && availableMonths.includes(selectedMonth)) {
      setVisibleMonth(selectedMonth);
    }
  }, [availableMonths, selectedDate, visibleMonth]);

  useEffect(() => {
    if (availableMonths.length === 0) {
      return;
    }

    if (!availableMonths.includes(visibleMonth)) {
      setVisibleMonth(
        availableMonths.includes(monthKeyFromDate(selectedDate))
          ? monthKeyFromDate(selectedDate)
          : availableMonths[0],
      );
    }
  }, [availableMonths, selectedDate, visibleMonth]);

  const monthCells = useMemo(
    () => buildMonthCells(visibleMonth, rowsByDate),
    [rowsByDate, visibleMonth],
  );
  const selectedRow = rowsByDate.get(selectedDate) ?? null;
  const visibleMonthIndex = availableMonths.indexOf(visibleMonth);
  const dayTrades = useMemo(
    () => trades.filter((trade) => trade.time.startsWith(selectedDate)),
    [trades, selectedDate],
  );

  function changeMonth(offset: -1 | 1) {
    const fallbackMonth = shiftMonthKey(visibleMonth, offset);
    const targetMonth = availableMonths[visibleMonthIndex + offset] ?? fallbackMonth;
    setVisibleMonth(targetMonth);

    if (monthKeyFromDate(selectedDate) !== targetMonth) {
      const nextRow = rows.find((row) => monthKeyFromDate(row.date) === targetMonth);

      if (nextRow) {
        onSelectDate(nextRow.date);
      }
    }
  }

  if (rows.length === 0) {
    return (
      <section className="calendar-layout">
        <div className="daily-detail-panel">
          <div className="daily-detail-empty">暂无已收盘收益数据</div>
        </div>
      </section>
    );
  }

  return (
    <section className="calendar-layout">
      <div className="pnl-linked-grid">
        <div className="calendar-panel compact-calendar-panel">
          <div className="calendar-panel-head compact-calendar-head">
            <div>
              <p className="calendar-kicker">Month view</p>
              <h3>{monthLabel(visibleMonth)}</h3>
            </div>
            <div className="calendar-nav">
              <button
                type="button"
                className="calendar-nav-button"
                onClick={() => changeMonth(-1)}
                disabled={availableMonths.length > 0 && visibleMonthIndex <= 0}
                aria-label="上个月"
              >
                ←
              </button>
              <button
                type="button"
                className="calendar-nav-button"
                onClick={() => changeMonth(1)}
                disabled={
                  availableMonths.length > 0 && visibleMonthIndex >= availableMonths.length - 1
                }
                aria-label="下个月"
              >
                →
              </button>
            </div>
          </div>
          <div className="calendar-weekdays" aria-hidden="true">
            {WEEKDAY_LABELS.map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
          <div className="calendar-grid compact-calendar-grid">
            {monthCells.map((cell, index) => {
              if (!cell) {
                return (
                  <div
                    key={`blank-${visibleMonth}-${index}`}
                    className="calendar-cell calendar-cell-blank compact-calendar-cell"
                    aria-hidden="true"
                  />
                );
              }

              const isSelected = selectedDate === cell.date;
              const hasMetrics = Boolean(cell.data);

              if (!cell.data) {
                return (
                  <div
                    key={cell.date}
                    className="calendar-cell compact-calendar-cell calendar-cell-blank"
                    aria-hidden="true"
                  >
                    <div className="day-card-head compact-day-card-head">
                      <strong>{cell.dayNumber}</strong>
                    </div>
                  </div>
                );
              }

              return (
                <button
                  key={cell.date}
                  type="button"
                  className={[
                    "day-card",
                    "compact-day-card",
                    isSelected ? "selected" : "",
                    hasMetrics ? "" : "is-empty",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => onSelectDate(cell.date)}
                >
                  <div className="day-card-head compact-day-card-head">
                    <strong>{cell.dayNumber}</strong>
                    <span>{formatNumber(cell.data.tradeCount)} 笔</span>
                  </div>
                  <div className="compact-day-card-body">
                    <strong className={cell.data.dailyPnl >= 0 ? "up" : "down"}>
                      {formatCurrency(cell.data.dailyPnl)}
                    </strong>
                    <small className={cell.data.dailyReturn >= 0 ? "up" : "down"}>
                      {formatPercent(cell.data.dailyReturn)}
                    </small>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
        <article className="daily-detail-panel">
          <div className="daily-detail-header">
            <div className="daily-detail-title-block">
              <div className="daily-detail-title-row">
                <h3>交易日明细</h3>
              </div>
            </div>
            <div className="daily-detail-date-block">
              <strong>{selectedDate}</strong>
            </div>
          </div>

          <div className="daily-detail-summary-grid">
            <article className="daily-summary-card">
              <span>当日收益</span>
              <strong className={selectedRow ? (selectedRow.dailyPnl < 0 ? "down" : "up") : ""}>
                {selectedRow ? formatCurrency(selectedRow.dailyPnl) : "--"}
              </strong>
            </article>
            <article className="daily-summary-card">
              <span>收益率</span>
              <strong className={selectedRow ? (selectedRow.dailyReturn < 0 ? "down" : "up") : ""}>
                {selectedRow ? formatPercent(selectedRow.dailyReturn) : "--"}
              </strong>
            </article>
            <article className="daily-summary-card">
              <span>成交笔数</span>
              <strong>{formatNumber(dayTrades.length)}</strong>
            </article>
          </div>

          <div className="daily-detail-content">
            <div className="daily-detail-table-shell">
              <div className="daily-detail-table-head pnl-simple-head">
                <span>股票代码</span>
                <span>名称</span>
                <span>当日盈亏</span>
                <span>收益率</span>
              </div>
              <div className="daily-detail-table-body">
                {details.length > 0 ? (
                  details.map((row) => (
                    <div key={row.symbol} className="daily-detail-row pnl-simple-row">
                      <span className="detail-cell detail-cell-symbol">{row.symbol}</span>
                      <span className="detail-cell detail-cell-name">{row.name}</span>
                      <span className={`detail-cell ${row.dailyPnl >= 0 ? "up" : "down"}`}>
                        {formatCurrency(row.dailyPnl)}
                      </span>
                      <span className={`detail-cell ${row.dailyReturn >= 0 ? "up" : "down"}`}>
                        {formatPercent(row.dailyReturn)}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="daily-detail-empty">当日无持仓收益记录</div>
                )}
              </div>
            </div>

            <div className="daily-trades-section">
              <h4 className="daily-trades-title">成交流水明细</h4>
              <div className="daily-detail-table-shell">
                <div className="daily-detail-table-head trades-head">
                  <span>成交时间</span>
                  <span>股票代码</span>
                  <span>名称</span>
                  <span>方向</span>
                  <span>委托价</span>
                  <span>成交价</span>
                  <span>股数</span>
                </div>
                <div className="daily-detail-table-body">
                  {dayTrades.length > 0 ? (
                    dayTrades.map((trade) => (
                      <div key={trade.id} className="daily-detail-row trades-row">
                        <span className="detail-cell">{trade.time.slice(11, 19)}</span>
                        <span className="detail-cell detail-cell-symbol">{trade.symbol}</span>
                        <span className="detail-cell detail-cell-name">{trade.name}</span>
                        <span className={`detail-cell ${trade.side === "BUY" ? "up" : "down"}`}>
                          {trade.side === "BUY" ? "买入" : "卖出"}
                        </span>
                        <span className="detail-cell">{trade.orderPrice.toFixed(2)}</span>
                        <span className="detail-cell">{trade.fillPrice?.toFixed(2) ?? "-"}</span>
                        <span className="detail-cell">{formatNumber(trade.shares)}</span>
                      </div>
                    ))
                  ) : (
                    <div className="daily-detail-empty">当日无成交记录</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </article>
      </div>
    </section>
  );
}
