import { useEffect, useMemo, useState } from "react";

import { tradeSideLabel } from "../orderHelpers";
import type { HistoryRow } from "../types";
import { formatCurrency, formatNumber } from "../utils";

type HistoryTabProps = {
  rows: HistoryRow[];
  extraDates: string[];
};

function tradeDateOf(value: string) {
  return value.slice(0, 10);
}

export function HistoryTab({ rows, extraDates }: HistoryTabProps) {
  const historyDates = useMemo(
    () => Array.from(new Set(rows.map((row) => tradeDateOf(row.time)))).sort(),
    [rows],
  );
  const availableDates = useMemo(
    () => Array.from(new Set([...historyDates, ...extraDates].filter(Boolean))).sort(),
    [extraDates, historyDates],
  );
  const earliestDate = availableDates[0] ?? "";
  const latestDate = availableDates[availableDates.length - 1] ?? "";
  const latestHistoryDate = historyDates[historyDates.length - 1] ?? latestDate;
  const [filterMode, setFilterMode] = useState<"single" | "range">("range");
  const [singleDate, setSingleDate] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  useEffect(() => {
    if (availableDates.length === 0) {
      setSingleDate("");
      setStartDate("");
      setEndDate("");
      return;
    }

    setSingleDate((current) =>
      current !== "" && current >= earliestDate && current <= latestDate
        ? current
        : latestHistoryDate,
    );
    setStartDate((current) =>
      current !== "" && current >= earliestDate && current <= latestDate ? current : earliestDate,
    );
    setEndDate((current) =>
      current !== "" && current >= earliestDate && current <= latestDate ? current : latestDate,
    );
  }, [availableDates.length, earliestDate, latestDate, latestHistoryDate]);

  const normalizedSingleDate = singleDate || latestHistoryDate;
  const rangeStartCandidate = startDate || earliestDate;
  const rangeEndCandidate = endDate || latestDate;
  const [normalizedStartDate, normalizedEndDate] =
    rangeStartCandidate <= rangeEndCandidate
      ? [rangeStartCandidate, rangeEndCandidate]
      : [rangeEndCandidate, rangeStartCandidate];

  const filteredRows = useMemo(
    () =>
      rows.filter((row) => {
        const tradeDate = tradeDateOf(row.time);

        if (filterMode === "single") {
          return normalizedSingleDate === "" || tradeDate === normalizedSingleDate;
        }

        return (
          (normalizedStartDate === "" || tradeDate >= normalizedStartDate) &&
          (normalizedEndDate === "" || tradeDate <= normalizedEndDate)
        );
      }),
    [filterMode, normalizedEndDate, normalizedSingleDate, normalizedStartDate, rows],
  );

  const visibleTradeDays = useMemo(
    () => new Set(filteredRows.map((row) => tradeDateOf(row.time))).size,
    [filteredRows],
  );
  const totalTurnover = useMemo(
    () => filteredRows.reduce((sum, row) => sum + (row.fillPrice ?? 0) * row.shares, 0),
    [filteredRows],
  );
  const filterRangeLabel =
    filterMode === "single"
      ? normalizedSingleDate || "全部交易日"
      : normalizedStartDate === normalizedEndDate
        ? normalizedStartDate || "全部交易日"
        : `${normalizedStartDate || earliestDate} 至 ${normalizedEndDate || latestDate}`;

  function resetHistoryFilters() {
    setFilterMode("range");
    setSingleDate(latestHistoryDate);
    setStartDate(earliestDate);
    setEndDate(latestDate);
  }

  function handleStartDateChange(nextValue: string) {
    setStartDate(nextValue);
    setEndDate((current) => {
      if (nextValue === "") {
        return current;
      }

      if (current === "" || current < nextValue) {
        return nextValue;
      }

      return current;
    });
  }

  function handleEndDateChange(nextValue: string) {
    setEndDate(nextValue);
    setStartDate((current) => {
      if (nextValue === "") {
        return current;
      }

      if (current === "" || current > nextValue) {
        return nextValue;
      }

      return current;
    });
  }

  return (
    <section className="history-layout">
      <div className="history-toolbar">
        <div className="history-filter-group">
          <span className="history-toolbar-label">交易日筛选</span>
          <div className="history-mode-switch" role="tablist" aria-label="历史流水筛选方式">
            <button
              type="button"
              className={
                filterMode === "single" ? "history-mode-button active" : "history-mode-button"
              }
              onClick={() => setFilterMode("single")}
            >
              单日
            </button>
            <button
              type="button"
              className={
                filterMode === "range" ? "history-mode-button active" : "history-mode-button"
              }
              onClick={() => setFilterMode("range")}
            >
              连续多日
            </button>
          </div>
        </div>

        <div className="history-filter-fields">
          {filterMode === "single" ? (
            <label className="history-filter-field">
              <span>交易日</span>
              <input
                type="date"
                value={singleDate}
                min={earliestDate || undefined}
                max={latestDate || undefined}
                onChange={(event) => setSingleDate(event.target.value)}
              />
            </label>
          ) : (
            <>
              <label className="history-filter-field">
                <span>起始日</span>
                <input
                  type="date"
                  value={startDate}
                  min={earliestDate || undefined}
                  max={latestDate || undefined}
                  onChange={(event) => handleStartDateChange(event.target.value)}
                />
              </label>
              <label className="history-filter-field">
                <span>结束日</span>
                <input
                  type="date"
                  value={endDate}
                  min={earliestDate || undefined}
                  max={latestDate || undefined}
                  onChange={(event) => handleEndDateChange(event.target.value)}
                />
              </label>
            </>
          )}
          <button type="button" className="history-reset-button" onClick={resetHistoryFilters}>
            重置
          </button>
        </div>

        <div className="history-toolbar-meta">
          <span>{filterRangeLabel}</span>
          <span>{formatNumber(visibleTradeDays)} 个交易日</span>
          <span>{formatNumber(filteredRows.length)} 笔成交</span>
          <strong>{formatCurrency(totalTurnover)}</strong>
        </div>
      </div>

      <div className="table-wrap history-table-wrap">
        <table className="history-table">
          <colgroup>
            <col className="history-col-time" />
            <col className="history-col-security" />
            <col className="history-col-side" />
            <col className="history-col-order" />
            <col className="history-col-fill" />
            <col className="history-col-turnover" />
            <col className="history-col-lots" />
            <col className="history-col-shares" />
          </colgroup>
          <thead>
            <tr>
              <th>成交时间</th>
              <th>证券</th>
              <th>方向</th>
              <th className="align-right">委托价</th>
              <th className="align-right">成交价</th>
              <th className="align-right">成交额</th>
              <th className="align-right">手数</th>
              <th className="align-right">股数</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.length > 0 ? (
              filteredRows.map((row) => {
                const turnover = row.fillPrice === undefined ? null : row.fillPrice * row.shares;

                return (
                  <tr key={row.id}>
                    <td>
                      <div className="history-time-cell">
                        <strong>{row.time.slice(11, 19)}</strong>
                        <span>{tradeDateOf(row.time)}</span>
                      </div>
                    </td>
                    <td>
                      <div className="history-security-cell">
                        <strong>{row.symbol}</strong>
                        <span>{row.name}</span>
                      </div>
                    </td>
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
                    <td className="number-cell">{row.orderPrice.toFixed(2)}</td>
                    <td className="number-cell">{row.fillPrice?.toFixed(2) ?? "-"}</td>
                    <td
                      className={
                        turnover === null
                          ? "number-cell"
                          : row.side === "BUY"
                            ? "number-cell up"
                            : "number-cell down"
                      }
                    >
                      {turnover === null ? "-" : formatCurrency(turnover)}
                    </td>
                    <td className="number-cell">{formatNumber(row.lots)}</td>
                    <td className="number-cell">{formatNumber(row.shares)}</td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={8} className="empty-state">
                  {rows.length > 0 ? "无成交记录" : "当前无历史流水"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
