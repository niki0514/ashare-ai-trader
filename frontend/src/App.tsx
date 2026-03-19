import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { api, type ManualImportRowInput } from "./api";
import type {
  CalendarDay,
  DailyPnlDetailRow,
  DashboardResponse,
  HistoryRow,
  MarketStatus,
  PendingOrderRow,
  ImportPreviewResponse,
  ImportPreviewRow,
  PositionRow
} from "./types";
import { formatCurrency, formatNumber, formatPercent, orderStatusLabel, statusLabel } from "./utils";

type TabKey = "positions" | "history" | "pnl" | "import";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "positions", label: "持仓明细" },
  { key: "history", label: "历史流水" },
  { key: "pnl", label: "每日收益" },
  { key: "import", label: "数据导入" }
];

const WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"];

type ManualInputRow = ManualImportRowInput & {
  id: string;
};

const MANUAL_SIDE_OPTIONS: Array<{ value: ManualImportRowInput["side"]; label: string }> = [
  { value: "BUY", label: "买入" },
  { value: "SELL", label: "卖出" }
];

const MANUAL_VALIDITY_OPTIONS: Array<{ value: ManualImportRowInput["validity"]; label: string }> = [
  { value: "DAY", label: "当日有效" },
  { value: "GTC", label: "持续有效" }
];

function createManualInputRow(): ManualInputRow {
  return {
    id: typeof crypto !== "undefined" && typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
    symbol: "",
    side: "BUY",
    price: 0,
    lots: 1,
    validity: "DAY"
  };
}

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
    new Date(year, month - 1 + offset, 1).getMonth() + 1
  ).padStart(2, "0")}`;
}

function nextTradingDate(tradeDate: string) {
  const [year, month, day] = tradeDate.split("-").map(Number);
  const nextDate = new Date(year, month - 1, day);

  do {
    nextDate.setDate(nextDate.getDate() + 1);
  } while (nextDate.getDay() === 0 || nextDate.getDay() === 6);

  const nextYear = nextDate.getFullYear();
  const nextMonth = String(nextDate.getMonth() + 1).padStart(2, "0");
  const nextDay = String(nextDate.getDate()).padStart(2, "0");
  return `${nextYear}-${nextMonth}-${nextDay}`;
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
      data: rowsByDate.get(date) ?? null
    };
  });
}

export default function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("positions");
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [pendingOrders, setPendingOrders] = useState<PendingOrderRow[]>([]);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [calendar, setCalendar] = useState<CalendarDay[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>("2026-03-18");
  const [dailyDetail, setDailyDetail] = useState<DailyPnlDetailRow[]>([]);
  const [previewRows, setPreviewRows] = useState<ImportPreviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string>("");

  async function loadCoreData(currentSelectedDate: string) {
    const [dashboardRes, positionsRes, pendingOrdersRes, historyRes, calendarRes, dailyRes] = await Promise.all([
      api.getDashboard(),
      api.getPositions(),
      api.getPendingOrders(),
      api.getHistory(),
      api.getCalendar(),
      api.getDailyPnlDetail(currentSelectedDate)
    ]);

    setDashboard(dashboardRes);
    setPositions(positionsRes.rows);
    setPendingOrders(pendingOrdersRes.rows);
    setHistory(historyRes.rows);
    setCalendar(calendarRes.rows);
    setDailyDetail(dailyRes.rows);
  }

  useEffect(() => {
    async function bootstrap() {
      setLoading(true);
      setErrorMessage("");

      try {
        await loadCoreData(selectedDate);
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "加载失败");
      } finally {
        setLoading(false);
      }
    }

    void bootstrap();
  }, []);

  useEffect(() => {
    async function loadDaily() {
      try {
        const response = await api.getDailyPnlDetail(selectedDate);
        setDailyDetail(response.rows);
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "加载失败");
      }
    }

    void loadDaily();
  }, [selectedDate]);

  useEffect(() => {
    if (!dashboard) {
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        await loadCoreData(selectedDate);
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "刷新失败");
      }
    }, 1000);

    return () => window.clearInterval(timer);
  }, [dashboard, selectedDate]);

  if (loading || !dashboard) {
    return <div className="loading-shell">{errorMessage || "Loading trading dashboard..."}</div>;
  }

  return (
    <div className="app-shell">
      <header className="top-shell compact-top-shell">
        <div className="meta-cluster meta-cluster-left">
          <span>交易日 {dashboard.tradeDate}</span>
          <span>最新更新 {new Date(dashboard.updatedAt).toLocaleTimeString("zh-CN")}</span>
        </div>
        <div className="meta-cluster meta-cluster-right">
          <span className={`status-pill market-${dashboard.marketStatus}`}>{statusLabel(dashboard.marketStatus)}</span>
        </div>
      </header>

      <section className="metric-grid">
        <MetricCard label="总资产" value={formatCurrency(dashboard.metrics.totalAssets)} />
        <MetricCard label="可用现金" value={formatCurrency(dashboard.metrics.availableCash)} />
        <MetricCard label="持仓市值" value={formatCurrency(dashboard.metrics.positionMarketValue)} />
        <MetricCard label="当日收益" value={formatCurrency(dashboard.metrics.dailyPnl)} accent={dashboard.metrics.dailyPnl} />
        <MetricCard label="累计收益" value={formatCurrency(dashboard.metrics.cumulativePnl)} accent={dashboard.metrics.cumulativePnl} />
        <MetricCard label="仓位比例" value={formatPercent(dashboard.metrics.exposureRatio)} />
      </section>

      <nav className="tab-row">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={tab.key === activeTab ? "tab active" : "tab"}
            onClick={() => setActiveTab(tab.key)}
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main className="panel-shell">
        {activeTab === "positions" && <PositionsTab rows={positions} />}
        {activeTab === "history" && <HistoryTab rows={history} />}
        {activeTab === "pnl" && (
          <PnlTab rows={calendar} selectedDate={selectedDate} onSelectDate={setSelectedDate} details={dailyDetail} trades={history} />
        )}
        {activeTab === "import" && (
          <ImportTab
            marketStatus={dashboard.marketStatus}
            targetTradeDate={nextTradingDate(dashboard.tradeDate)}
            previewRows={previewRows}
            onPreviewUpdate={(response) => {
              setPreviewRows(response.rows);
            }}
          />
        )}
      </main>
    </div>
  );
}

function MetricCard({ label, value, accent }: { label: string; value: string; accent?: number }) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong className={accent === undefined ? "" : accent >= 0 ? "up" : "down"}>{value}</strong>
    </article>
  );
}

function PositionsTab({ rows }: { rows: PositionRow[] }) {
  const rowsWithPendingOrders = rows.filter((row) => row.pendingOrders.length > 0);

  return (
    <section className="positions-layout">
      <DataTable
        headers={["股票代码", "名称", "持仓数量", "可卖数量", "卖出冻结数量", "成本价", "现价", "市值", "今日盈亏", "今日盈亏比例", "浮盈亏", "收益率"]}
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
                <td className={row.todayPnl >= 0 ? "up" : "down"}>{formatCurrency(row.todayPnl)}</td>
                <td className={row.todayReturn >= 0 ? "up" : "down"}>{formatPercent(row.todayReturn)}</td>
                <td className={row.pnl >= 0 ? "up" : "down"}>{formatCurrency(row.pnl)}</td>
                <td className={row.returnRate >= 0 ? "up" : "down"}>{formatPercent(row.returnRate)}</td>
              </tr>
            ))
            : [
                <tr key="empty-positions">
                  <td colSpan={12} className="empty-state">当前无持仓</td>
                </tr>
              ]
        }
      />

      <div className="section-head compact">
        <h3>挂单明细</h3>
        <span>{rowsWithPendingOrders.length > 0 ? `涉及 ${formatNumber(rowsWithPendingOrders.length)} 只持仓` : "当前无卖出挂单"}</span>
      </div>
      <div className="pending-sections">
        {rowsWithPendingOrders.length > 0 ? (
          rowsWithPendingOrders.map((row) => (
            <article key={`${row.symbol}-pending-card`} className="pending-orders-box">
              <table className="pending-orders-table">
                <thead>
                  <tr>
                    <th>股票代码</th>
                    <th>名称</th>
                    <th>操作</th>
                    <th>委托数量</th>
                    <th>委托价格</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {row.pendingOrders.map((order) => (
                    <tr key={order.id}>
                      <td>{row.symbol}</td>
                      <td>{row.name}</td>
                      <td>{order.side === "BUY" ? "买入" : "卖出"}</td>
                      <td>{formatNumber(order.shares)}</td>
                      <td>{order.price.toFixed(2)}</td>
                      <td>{orderStatusLabel(order.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </article>
          ))
        ) : (
          <div className="empty-panel">当前无卖出挂单</div>
        )}
      </div>
    </section>
  );
}

function HistoryTab({ rows }: { rows: HistoryRow[] }) {
  return (
    <section>
      <DataTable
        headers={["成交时间", "股票代码", "名称", "方向", "委托价", "成交价", "手数", "股数"]}
        rows={rows.map((row) => (
          <tr key={row.id}>
             <td>{row.time}</td>
            <td>{row.symbol}</td>
            <td>{row.name}</td>
            <td>{row.side}</td>
            <td>{row.orderPrice.toFixed(2)}</td>
            <td>{row.fillPrice?.toFixed(2) ?? "-"}</td>
            <td>{row.lots}</td>
            <td>{formatNumber(row.shares)}</td>
          </tr>
        ))}
      />
    </section>
  );
}

function PnlTab({
  rows,
  selectedDate,
  onSelectDate,
  details,
  trades
}: {
  rows: CalendarDay[];
  selectedDate: string;
  onSelectDate: (date: string) => void;
  details: DailyPnlDetailRow[];
  trades: HistoryRow[];
}) {
  const rowsByDate = useMemo(() => new Map(rows.map((row) => [row.date, row])), [rows]);
  const availableMonths = useMemo(
    () => Array.from(new Set(rows.map((row) => monthKeyFromDate(row.date)))).sort(),
    [rows]
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
      setVisibleMonth(availableMonths.includes(monthKeyFromDate(selectedDate)) ? monthKeyFromDate(selectedDate) : availableMonths[0]);
    }
  }, [availableMonths, selectedDate, visibleMonth]);

  const monthCells = useMemo(() => buildMonthCells(visibleMonth, rowsByDate), [rowsByDate, visibleMonth]);
  const selectedRow = rowsByDate.get(selectedDate) ?? null;
  const visibleMonthIndex = availableMonths.indexOf(visibleMonth);
  const dayTrades = useMemo(
    () => trades.filter((t) => t.time.startsWith(selectedDate)),
    [trades, selectedDate]
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
                disabled={availableMonths.length > 0 && visibleMonthIndex >= availableMonths.length - 1}
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
                return <div key={`blank-${visibleMonth}-${index}`} className="calendar-cell calendar-cell-blank compact-calendar-cell" aria-hidden="true" />;
              }

              const isSelected = selectedDate === cell.date;
              const isActive = Boolean(cell.data);

              return (
                <button
                  key={cell.date}
                  type="button"
                  className={[
                    "day-card",
                    "compact-day-card",
                    isSelected ? "selected" : "",
                    isActive ? "" : "is-empty"
                  ].filter(Boolean).join(" ")}
                  onClick={() => onSelectDate(cell.date)}
                >
                  <div className="day-card-head compact-day-card-head">
                    <strong>{cell.dayNumber}</strong>
                    {cell.data ? <span>{formatNumber(cell.data.tradeCount)} 笔</span> : <span>休市</span>}
                  </div>
                  {cell.data ? (
                    <div className="compact-day-card-body">
                      <strong className={cell.data.dailyPnl >= 0 ? "up" : "down"}>{formatCurrency(cell.data.dailyPnl)}</strong>
                      <small className={cell.data.dailyReturn >= 0 ? "up" : "down"}>{formatPercent(cell.data.dailyReturn)}</small>
                    </div>
                  ) : (
                    <div className="day-card-empty compact-day-card-empty">
                      <small>暂无数据</small>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
        <article className="daily-detail-panel">
          <div className="daily-detail-header">
            <div className="daily-detail-title-block">
              <div className="daily-detail-title-row">
                <h3>交易日损益明细</h3>
              </div>
            </div>
            <div className="daily-detail-date-block">
              <span className="daily-detail-date-label">选中日期</span>
              <strong>{selectedDate}</strong>
              <span>{selectedRow ? "组合当日收益" : "当前日期暂无收益汇总"}</span>
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
                    <span className={`detail-cell ${row.dailyPnl >= 0 ? "up" : "down"}`}>{formatCurrency(row.dailyPnl)}</span>
                    <span className={`detail-cell ${row.dailyReturn >= 0 ? "up" : "down"}`}>{formatPercent(row.dailyReturn)}</span>
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
                  dayTrades.map((t) => (
                    <div key={t.id} className="daily-detail-row trades-row">
                      <span className="detail-cell">{t.time.slice(11, 19)}</span>
                      <span className="detail-cell detail-cell-symbol">{t.symbol}</span>
                      <span className="detail-cell detail-cell-name">{t.name}</span>
                      <span className={`detail-cell ${t.side === "BUY" ? "up" : "down"}`}>{t.side === "BUY" ? "买入" : "卖出"}</span>
                      <span className="detail-cell">{t.orderPrice.toFixed(2)}</span>
                      <span className="detail-cell">{t.fillPrice?.toFixed(2) ?? "-"}</span>
                      <span className="detail-cell">{formatNumber(t.shares)}</span>
                    </div>
                  ))
                ) : (
                  <div className="daily-detail-empty">当日无成交记录</div>
                )}
              </div>
            </div>
          </div>
        </article>
      </div>
    </section>
  );
}

function ImportTab({
  marketStatus,
  targetTradeDate,
  previewRows,
  onPreviewUpdate
}: {
  marketStatus: MarketStatus;
  targetTradeDate: string;
  previewRows: ImportPreviewRow[];
  onPreviewUpdate: (response: ImportPreviewResponse) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);
  const [manualSubmitting, setManualSubmitting] = useState(false);
  const [manualRows, setManualRows] = useState<ManualInputRow[]>([createManualInputRow()]);
  const isImportWindowOpen = marketStatus === "pre_open" || marketStatus === "closed";

  const hasManualInput = manualRows.some((row) => {
    return row.symbol.trim() !== "" || row.price > 0 || row.lots > 0;
  });

  function guardImportWindow() {
    return isImportWindowOpen;
  }

  function updateManualRow<K extends keyof ManualImportRowInput>(id: string, key: K, value: ManualImportRowInput[K]) {
    setManualRows((currentRows) => currentRows.map((row) => (row.id === id ? { ...row, [key]: value } : row)));
  }

  function addManualRow() {
    setManualRows((currentRows) => [...currentRows, createManualInputRow()]);
  }

  function removeManualRow(id: string) {
    setManualRows((currentRows) => {
      if (currentRows.length === 1) {
        return [createManualInputRow()];
      }

      return currentRows.filter((row) => row.id !== id);
    });
  }

  function resetManualRows() {
    setManualRows([createManualInputRow()]);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFile = event.target.files?.[0] ?? null;
    setSelectedFile(nextFile);
  }

  async function handleUpload() {
    if (!guardImportWindow()) {
      return;
    }

    if (!selectedFile) {
      return;
    }

    setUploading(true);

    try {
      const response = await api.uploadImportFile({
        file: selectedFile,
        targetTradeDate,
        mode: "DRAFT"
      });
      onPreviewUpdate(response);
    } catch {
      return;
    } finally {
      setUploading(false);
    }
  }

  async function handleManualSubmit() {
    if (!guardImportWindow()) {
      return;
    }

    const sanitizedRows = manualRows
      .map((row) => ({
        symbol: row.symbol.trim().toUpperCase(),
        side: row.side,
        price: Number(row.price),
        lots: Number(row.lots),
        validity: row.validity
      }))
      .filter((row) => row.symbol !== "" || row.price > 0 || row.lots > 0);

    if (sanitizedRows.length === 0) {
      return;
    }

    setManualSubmitting(true);

    try {
      const response = await api.previewImports({
        targetTradeDate,
        mode: "DRAFT",
        sourceType: "MANUAL",
        rows: sanitizedRows
      });

      onPreviewUpdate(response);
    } catch {
      return;
    } finally {
      setManualSubmitting(false);
    }
  }

  async function handleTemplateDownload() {
    if (!guardImportWindow()) {
      return;
    }

    setDownloadingTemplate(true);

    try {
      const blob = await api.downloadImportTemplate(targetTradeDate);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `import-template-${targetTradeDate}.xlsx`;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      return;
    } finally {
      setDownloadingTemplate(false);
    }
  }

  return (
    <section className="import-layout">
      <div className="import-overview-card compact-import-overview">
        <div className="import-overview-grid compact-import-summary-grid">
          <div className="import-overview-item">
            <span>目标交易日</span>
            <strong>{targetTradeDate}</strong>
          </div>
          <div className="import-overview-item">
            <span>市场状态</span>
            <strong>{statusLabel(marketStatus)}</strong>
          </div>
        </div>
      </div>

      <article className="input-card import-workflow-card">
        <div className="import-workflow-block">
          <div className="input-card-head">
            <h3>手动输入</h3>
          </div>
          <div className="manual-grid-shell">
            <div className="manual-grid-head">
              <button type="button" onClick={addManualRow}>新增一行</button>
            </div>
            <div className="manual-grid-table" role="table" aria-label="手动导入输入表格">
              <div className="manual-grid-header" role="row">
                <span>股票代码</span>
                <span>方向</span>
                <span>委托价</span>
                <span>手数</span>
                <span>有效期</span>
                <span>操作</span>
              </div>
              <div className="manual-grid-body">
                {manualRows.map((row, index) => (
                  <div key={row.id} className="manual-grid-row" role="row">
                    <label className="manual-field">
                      <span className="sr-only">第 {index + 1} 行股票代码</span>
                      <input
                        value={row.symbol}
                        onChange={(event) => updateManualRow(row.id, "symbol", event.target.value.toUpperCase())}
                        placeholder="如 600519"
                      />
                    </label>
                    <label className="manual-field">
                      <span className="sr-only">第 {index + 1} 行方向</span>
                      <select value={row.side} onChange={(event) => updateManualRow(row.id, "side", event.target.value as ManualImportRowInput["side"])}>
                        {MANUAL_SIDE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                    <label className="manual-field">
                      <span className="sr-only">第 {index + 1} 行委托价</span>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={row.price}
                        onChange={(event) => updateManualRow(row.id, "price", Number(event.target.value))}
                        placeholder="0.00"
                      />
                    </label>
                    <label className="manual-field">
                      <span className="sr-only">第 {index + 1} 行手数</span>
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={row.lots}
                        onChange={(event) => updateManualRow(row.id, "lots", Number(event.target.value))}
                        placeholder="1"
                      />
                    </label>
                    <label className="manual-field">
                      <span className="sr-only">第 {index + 1} 行有效期</span>
                      <select
                        value={row.validity}
                        onChange={(event) => updateManualRow(row.id, "validity", event.target.value as ManualImportRowInput["validity"])}
                      >
                        {MANUAL_VALIDITY_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                    <div className="manual-row-actions">
                      <button type="button" onClick={() => removeManualRow(row.id)} disabled={manualSubmitting}>删除</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="button-row">
            <button type="button" onClick={resetManualRows} disabled={manualSubmitting}>清空输入</button>
            <button type="button" onClick={() => void handleManualSubmit()} disabled={manualSubmitting || !hasManualInput || !isImportWindowOpen}>
              {manualSubmitting ? "解析中..." : "提交并解析"}
            </button>
          </div>
        </div>

        <div className="import-workflow-divider" aria-hidden="true" />

        <div className="import-workflow-block">
          <div className="input-card-head">
            <h3>Excel 导入</h3>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
          <div className="validation-note">{selectedFile ? selectedFile.name : ""}</div>
          <div className="button-row">
            <button type="button" onClick={() => void handleTemplateDownload()} disabled={uploading || downloadingTemplate || manualSubmitting || !isImportWindowOpen}>
              {downloadingTemplate ? "下载中..." : "下载模板"}
            </button>
            <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading || downloadingTemplate || !isImportWindowOpen}>选择文件</button>
            <button type="button" onClick={() => void handleUpload()} disabled={uploading || downloadingTemplate || !selectedFile || !isImportWindowOpen}>
              {uploading ? "上传中..." : "上传并解析"}
            </button>
          </div>
        </div>
      </article>

      <DataTable
        headers={["行号", "股票代码", "方向", "委托价", "手数", "有效期", "校验结果"]}
        rows={
          previewRows.length > 0
            ? previewRows.map((row) => (
                <tr key={row.rowNumber}>
                  <td>{row.rowNumber}</td>
                  <td>{row.symbol}</td>
                  <td>{row.side}</td>
                  <td>{row.price.toFixed(2)}</td>
                  <td>{row.lots}</td>
                  <td>{row.validity}</td>
                  <td>
                    <span className={`status-pill validation-${row.validationStatus.toLowerCase()}`}>
                      {row.validationStatus}
                    </span>
                    <div className="validation-note">{row.validationMessage}</div>
                  </td>
                </tr>
              ))
            : [
                <tr key="empty-import-preview">
                  <td colSpan={7} className="empty-state">提交手动输入或上传文件后，将在这里展示解析预览</td>
                </tr>
              ]
        }
      />
    </section>
  );
}

function DataTable({ headers, rows }: { headers: string[]; rows: ReactNode[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  );
}
