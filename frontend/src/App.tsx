import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  api,
  getActiveUserId as readActiveUserId,
  setActiveUserId as persistActiveUserId,
  type ManualImportRowInput,
} from "./api";
import type {
  CalendarDay,
  DailyPnlDetailRow,
  DashboardResponse,
  HistoryRow,
  LatestImportBatch,
  MarketStatus,
  PendingOrderRow,
  ImportPreviewRow,
  PositionRow,
  UserSummary,
} from "./types";
import {
  formatCurrency,
  formatNumber,
  formatPercent,
  orderStatusLabel,
  statusLabel,
} from "./utils";

type TabKey = "positions" | "history" | "pnl" | "import";
type ImportOrderFilter = "active" | "all" | "filled" | "cancelled" | "expired" | "rejected";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "positions", label: "持仓明细" },
  { key: "history", label: "历史流水" },
  { key: "pnl", label: "每日收益" },
  { key: "import", label: "操作录入" },
];
const CORE_DATA_POLL_MS = 3000;
const DEFAULT_NEW_USER_CASH = "500000";
const WORKFLOW_FEEDBACK_DURATION_MS = 2000;

const WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"];

type ManualInputRow = {
  id: string;
  symbol: string;
  side: ManualImportRowInput["side"];
  tradeDate: string;
  validity: ManualImportRowInput["validity"];
  price: string;
  lots: string;
  validationStatus: ImportPreviewRow["validationStatus"] | null;
  validationMessage: string;
};

const MANUAL_SIDE_OPTIONS: Array<{ value: ManualImportRowInput["side"]; label: string }> = [
  { value: "BUY", label: "买入" },
  { value: "SELL", label: "卖出" },
];

const MANUAL_VALIDITY_OPTIONS: Array<{
  value: ManualImportRowInput["validity"];
  label: string;
}> = [
  { value: "DAY", label: "当日挂单" },
  { value: "GTC", label: "持续挂单" },
];

const IMPORT_ORDER_FILTER_OPTIONS: Array<{ value: ImportOrderFilter; label: string }> = [
  { value: "active", label: "进行中" },
  { value: "all", label: "全部" },
  { value: "filled", label: "已成交" },
  { value: "cancelled", label: "已撤单" },
  { value: "expired", label: "已失效" },
  { value: "rejected", label: "已拒绝" },
];

function createManualInputRow(
  seed: Partial<
    ManualImportRowInput & {
      tradeDate: string;
      validationStatus: ImportPreviewRow["validationStatus"] | null;
      validationMessage: string;
    }
  > = {},
): ManualInputRow {
  return {
    id:
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`,
    symbol: seed.symbol ?? "",
    side: seed.side ?? "BUY",
    tradeDate: seed.tradeDate ?? "",
    validity: seed.validity ?? "DAY",
    price: seed.price === undefined ? "" : String(seed.price),
    lots: seed.lots === undefined ? "1" : String(seed.lots),
    validationStatus: seed.validationStatus ?? null,
    validationMessage: seed.validationMessage ?? "",
  };
}

function createManualRowsFromPreview(
  rows: ImportPreviewRow[],
  fallbackTradeDate: string,
): ManualInputRow[] {
  if (rows.length === 0) {
    return [createManualInputRow({ tradeDate: fallbackTradeDate })];
  }

  return rows.map((row) =>
    createManualInputRow({
      symbol: row.symbol,
      side: row.side,
      tradeDate: row.tradeDate || fallbackTradeDate,
      validity: row.validity,
      price: row.price,
      lots: row.lots,
      validationStatus: row.validationStatus,
      validationMessage: row.validationMessage,
    }),
  );
}

function createManualRowsFromBatch(batch: LatestImportBatch): ManualInputRow[] {
  if (batch.items.length === 0) {
    return [createManualInputRow({ tradeDate: batch.targetTradeDate })];
  }

  return batch.items.map((item) =>
    createManualInputRow({
      symbol: item.symbol,
      side: item.side,
      tradeDate: batch.targetTradeDate,
      validity: item.validity,
      price: item.limitPrice,
      lots: item.lots,
      validationStatus: item.validationStatus,
      validationMessage: item.validationMessage ?? "",
    }),
  );
}

function clearManualRowValidation(row: ManualInputRow): ManualInputRow {
  if (row.validationStatus === null && row.validationMessage === "") {
    return row;
  }

  return {
    ...row,
    validationStatus: null,
    validationMessage: "",
  };
}

function isManualRowTouched(row: ManualInputRow) {
  return (
    row.symbol.trim() !== "" ||
    row.price.trim() !== "" ||
    row.lots.trim() !== "1" ||
    row.side !== "BUY" ||
    row.validity !== "DAY"
  );
}

function parseManualNumber(value: string) {
  const trimmed = value.trim();
  return trimmed === "" ? Number.NaN : Number(trimmed);
}

function isManualRowComplete(row: ManualInputRow) {
  return (
    row.tradeDate.trim() !== "" &&
    row.symbol.trim() !== "" &&
    parseManualNumber(row.price) > 0 &&
    parseManualNumber(row.lots) > 0
  );
}

function importValidationSummary(rows: ManualInputRow[]) {
  return rows.reduce(
    (summary, row) => {
      if (row.validationStatus) {
        summary[row.validationStatus] += 1;
      }
      return summary;
    },
    { VALID: 0, WARNING: 0, ERROR: 0 },
  );
}

function importValidationLabel(status: ImportPreviewRow["validationStatus"] | "PENDING") {
  switch (status) {
    case "VALID":
      return "通过";
    case "WARNING":
      return "警告";
    case "ERROR":
      return "错误";
    default:
      return "待校验";
  }
}

function importRowValidationState(row: ManualInputRow, isDraftDirty: boolean) {
  if (!isManualRowTouched(row)) {
    return {
      badgeClassName: "status-pill validation-pending",
      label: "未填写",
      message: "可继续补充这一行，空白行不会参与校验和提交。",
    };
  }

  if (!isManualRowComplete(row)) {
    return {
      badgeClassName: "status-pill validation-pending",
      label: "待补全",
      message: "请补全挂单时间、股票代码、委托价和手数后再校验。",
    };
  }

  if (row.validationStatus) {
    return {
      badgeClassName: `status-pill validation-${row.validationStatus.toLowerCase()}`,
      label: importValidationLabel(row.validationStatus),
      message: row.validationMessage || "校验通过",
    };
  }

  return {
    badgeClassName: "status-pill validation-pending",
    label: "待校验",
    message: isDraftDirty ? "内容已修改，请重新校验。" : "点击“校验全部”获取最新结果。",
  };
}

function formatDraftSavedAt(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function currentDraftSavedAt() {
  return formatDraftSavedAt(new Date().toISOString());
}

function tradeSideLabel(side: "BUY" | "SELL") {
  return side === "BUY" ? "买入" : "卖出";
}

function orderValidityLabel(validity: ManualImportRowInput["validity"]) {
  return validity === "GTC" ? "持续挂单" : "当日挂单";
}

function isActivePendingOrderStatus(status: PendingOrderRow["status"]) {
  return status === "confirmed" || status === "pending" || status === "triggered";
}

function isPendingOrderEffectiveToday(order: PendingOrderRow, currentTradeDate: string) {
  if (!isActivePendingOrderStatus(order.status)) {
    return false;
  }

  if (order.tradeDate === currentTradeDate) {
    return true;
  }

  return order.validity === "GTC" && order.tradeDate < currentTradeDate;
}

function matchesImportOrderFilter(order: PendingOrderRow, filter: ImportOrderFilter) {
  if (filter === "all") {
    return true;
  }

  if (filter === "active") {
    return isActivePendingOrderStatus(order.status);
  }

  return order.status === filter;
}

function manualImportPayload(row: ManualInputRow): ManualImportRowInput {
  return {
    symbol: row.symbol.trim().toUpperCase(),
    side: row.side,
    price: parseManualNumber(row.price),
    lots: parseManualNumber(row.lots),
    validity: row.validity,
  };
}

function groupManualRowsByTradeDate(rows: ManualInputRow[]) {
  const grouped = new Map<
    string,
    Array<{
      rowId: string;
      payload: ManualImportRowInput;
    }>
  >();

  for (const row of rows) {
    const tradeDate = row.tradeDate.trim();
    const bucket = grouped.get(tradeDate) ?? [];
    bucket.push({
      rowId: row.id,
      payload: manualImportPayload(row),
    });
    grouped.set(tradeDate, bucket);
  }

  return Array.from(grouped.entries())
    .map(([tradeDate, items]) => ({ tradeDate, items }))
    .sort((a, b) => a.tradeDate.localeCompare(b.tradeDate));
}

function nextManualRowTradeDate(
  rows: ManualInputRow[],
  fallbackTradeDate: string,
  afterId?: string,
) {
  if (afterId) {
    const matched = rows.find((row) => row.id === afterId);
    if (matched?.tradeDate) {
      return matched.tradeDate;
    }
  }

  const lastTradeDate = [...rows]
    .reverse()
    .map((row) => row.tradeDate.trim())
    .find((value) => value !== "");

  return lastTradeDate ?? fallbackTradeDate;
}

function tradeDateOf(value: string) {
  return value.slice(0, 10);
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

export default function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("positions");
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [activeUserId, setActiveUserIdState] = useState<string>(readActiveUserId());
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [pendingOrders, setPendingOrders] = useState<PendingOrderRow[]>([]);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [calendar, setCalendar] = useState<CalendarDay[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>("2026-03-18");
  const [dailyDetail, setDailyDetail] = useState<DailyPnlDetailRow[]>([]);
  const [newUserName, setNewUserName] = useState("");
  const [newUserCash, setNewUserCash] = useState(DEFAULT_NEW_USER_CASH);
  const [showCreateUserForm, setShowCreateUserForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [usersLoaded, setUsersLoaded] = useState(false);
  const [userActionLoading, setUserActionLoading] = useState(false);
  const [deletingPendingOrderId, setDeletingPendingOrderId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const refreshingCoreDataRef = useRef(false);
  const createUserNameInputRef = useRef<HTMLInputElement | null>(null);
  const isDashboardReady = dashboard !== null;
  const shouldAutoRefresh =
    isDashboardReady && activeTab !== "import" && dashboard.marketStatus === "trading";
  const activeUser = users.find((user) => user.id === activeUserId) ?? null;

  function resetUserScopedData() {
    setDashboard(null);
    setPositions([]);
    setPendingOrders([]);
    setHistory([]);
    setCalendar([]);
    setDailyDetail([]);
  }

  async function loadCoreData(currentSelectedDate: string) {
    const [dashboardRes, positionsRes, pendingOrdersRes, historyRes, calendarRes, dailyRes] =
      await Promise.all([
        api.getDashboard(),
        api.getPositions(),
        api.getPendingOrders(),
        api.getHistory(),
        api.getCalendar(),
        api.getDailyPnlDetail(currentSelectedDate),
      ]);

    setDashboard(dashboardRes);
    setPositions(positionsRes.rows);
    setPendingOrders(pendingOrdersRes.rows);
    setHistory(historyRes.rows);
    setCalendar(calendarRes.rows);
    setDailyDetail(dailyRes.rows);
  }

  async function syncUsers(preferredUserId?: string) {
    const response = await api.getUsers();
    const nextUsers = response.rows;
    setUsersLoaded(true);
    setUsers(nextUsers);
    if (nextUsers.length === 0) {
      persistActiveUserId("");
      setActiveUserIdState("");
      return null;
    }

    const storedUserId = preferredUserId ?? readActiveUserId();
    const resolvedUserId = nextUsers.some((user) => user.id === storedUserId)
      ? storedUserId
      : nextUsers[0].id;

    persistActiveUserId(resolvedUserId);
    setActiveUserIdState(resolvedUserId);
    return resolvedUserId;
  }

  async function reloadForUser(nextUserId?: string, currentSelectedDate: string = selectedDate) {
    const resolvedUserId = await syncUsers(nextUserId);
    if (!resolvedUserId) {
      refreshingCoreDataRef.current = false;
      resetUserScopedData();
      return null;
    }
    if (resolvedUserId !== activeUserId) {
      refreshingCoreDataRef.current = false;
    }
    await loadCoreData(currentSelectedDate);
    return resolvedUserId;
  }

  useEffect(() => {
    async function bootstrap() {
      setLoading(true);
      setUsersLoaded(false);
      setErrorMessage("");

      try {
        await reloadForUser(readActiveUserId(), selectedDate);
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "加载失败");
      } finally {
        setLoading(false);
      }
    }

    void bootstrap();
  }, []);

  useEffect(() => {
    if (!showCreateUserForm) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !userActionLoading) {
        handleCancelCreateUser();
      }
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    createUserNameInputRef.current?.focus();
    createUserNameInputRef.current?.select();

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [showCreateUserForm, userActionLoading]);

  useEffect(() => {
    async function loadDaily() {
      if (!activeUserId) {
        setDailyDetail([]);
        return;
      }
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
    if (calendar.length === 0) {
      return;
    }

    if (!calendar.some((row) => row.date === selectedDate)) {
      setSelectedDate(calendar[calendar.length - 1].date);
    }
  }, [calendar, selectedDate]);

  useEffect(() => {
    if (!shouldAutoRefresh) {
      return;
    }

    let cancelled = false;
    let timer: number | null = null;

    const scheduleNextRefresh = () => {
      if (cancelled) {
        return;
      }

      timer = window.setTimeout(() => {
        void refreshCoreData();
      }, CORE_DATA_POLL_MS);
    };

    const refreshCoreData = async () => {
      if (cancelled || refreshingCoreDataRef.current) {
        scheduleNextRefresh();
        return;
      }

      refreshingCoreDataRef.current = true;

      try {
        await loadCoreData(selectedDate);
      } catch (error) {
        if (!cancelled) {
          setErrorMessage(error instanceof Error ? error.message : "刷新失败");
        }
      } finally {
        refreshingCoreDataRef.current = false;
      }
      scheduleNextRefresh();
    };

    scheduleNextRefresh();

    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [selectedDate, shouldAutoRefresh]);

  async function handleUserChange(nextUserId: string) {
    setUserActionLoading(true);
    setErrorMessage("");
    try {
      await reloadForUser(nextUserId);
      setNewUserName("");
      setNewUserCash(DEFAULT_NEW_USER_CASH);
      setShowCreateUserForm(false);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "切换账户失败");
    } finally {
      setUserActionLoading(false);
    }
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = newUserName.trim();
    if (trimmedName === "") {
      setErrorMessage("用户名称不能为空");
      return;
    }
    const initialCash = Number(newUserCash);
    if (!Number.isFinite(initialCash) || initialCash <= 0) {
      setErrorMessage("初始资金必须大于 0");
      return;
    }

    setUserActionLoading(true);
    setErrorMessage("");
    try {
      const created = await api.createUser({
        name: trimmedName,
        initialCash,
      });
      setNewUserName("");
      setNewUserCash(DEFAULT_NEW_USER_CASH);
      setShowCreateUserForm(false);
      await reloadForUser(created.id);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "创建账户失败");
    } finally {
      setUserActionLoading(false);
    }
  }

  function handleOpenCreateUserForm() {
    setErrorMessage("");
    setNewUserName("");
    setNewUserCash(DEFAULT_NEW_USER_CASH);
    setShowCreateUserForm(true);
  }

  function handleCancelCreateUser() {
    setErrorMessage("");
    setNewUserName("");
    setNewUserCash(DEFAULT_NEW_USER_CASH);
    setShowCreateUserForm(false);
  }

  async function handleDeletePendingOrder(order: PendingOrderRow) {
    if (!order.canDelete || deletingPendingOrderId) {
      return;
    }

    setDeletingPendingOrderId(order.id);
    setErrorMessage("");
    try {
      await api.deleteOrder(order.id);
      await loadCoreData(selectedDate);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "撤单失败");
    } finally {
      setDeletingPendingOrderId(null);
    }
  }

  if (loading) {
    return <div className="loading-shell">{errorMessage || "Loading trading dashboard..."}</div>;
  }

  if (!usersLoaded && errorMessage) {
    return <div className="loading-shell">{errorMessage}</div>;
  }

  if (!activeUser) {
    return (
      <div className="app-shell">
        <header className="top-shell compact-top-shell">
          <div className="meta-cluster meta-cluster-left">
            <span>当前暂无账户</span>
          </div>
        </header>

        <section className="empty-account-state">
          <div className="empty-account-card">
            <div className="section-head">
              <h2>创建首个账户</h2>
            </div>
            <p className="empty-account-copy">先创建一个账户，再开始记录持仓、流水和每日收益。</p>
            <button
              type="button"
              className="user-primary-button"
              disabled={userActionLoading}
              onClick={handleOpenCreateUserForm}
            >
              + 新建账户
            </button>
          </div>
        </section>

        {showCreateUserForm ? (
          <CreateUserModal
            name={newUserName}
            cash={newUserCash}
            errorMessage={errorMessage}
            loading={userActionLoading}
            inputRef={createUserNameInputRef}
            onNameChange={setNewUserName}
            onCashChange={setNewUserCash}
            onCancel={handleCancelCreateUser}
            onSubmit={handleCreateUser}
          />
        ) : null}
      </div>
    );
  }

  if (!dashboard) {
    return <div className="loading-shell">{errorMessage || "加载账户数据失败"}</div>;
  }

  return (
    <div className="app-shell">
      <header className="top-shell compact-top-shell">
        <div className="meta-cluster meta-cluster-left meta-cluster-primary">
          <span className={`status-pill market-${dashboard.marketStatus}`}>
            {statusLabel(dashboard.marketStatus)}
          </span>
          <span>交易日 {dashboard.tradeDate}</span>
          <span>最新更新 {new Date(dashboard.updatedAt).toLocaleTimeString("zh-CN")}</span>
        </div>
        <div className="account-toolbar">
          <label className="account-switcher">
            <span className="account-toolbar-label">账户</span>
            <div className="account-switcher-select">
              <select
                value={activeUserId}
                onChange={(event) => void handleUserChange(event.target.value)}
                disabled={userActionLoading || showCreateUserForm}
              >
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.name}
                  </option>
                ))}
              </select>
            </div>
          </label>
          <div className="account-summary-pill">
            <span className="account-toolbar-label">初始资金</span>
            <strong>{formatCurrency(activeUser.initialCash)}</strong>
          </div>
          <button
            type="button"
            className="user-primary-button account-create-button"
            disabled={userActionLoading}
            onClick={handleOpenCreateUserForm}
          >
            + 新建账户
          </button>
        </div>
      </header>

      {errorMessage && !showCreateUserForm ? (
        <div className="user-feedback user-feedback-error">{errorMessage}</div>
      ) : null}

      {showCreateUserForm ? (
        <CreateUserModal
          name={newUserName}
          cash={newUserCash}
          errorMessage={errorMessage}
          loading={userActionLoading}
          inputRef={createUserNameInputRef}
          onNameChange={setNewUserName}
          onCashChange={setNewUserCash}
          onCancel={handleCancelCreateUser}
          onSubmit={handleCreateUser}
        />
      ) : null}

      <section className="metric-grid">
        <MetricCard label="总资产" value={formatCurrency(dashboard.metrics.totalAssets)} />
        <MetricCard label="可用现金" value={formatCurrency(dashboard.metrics.availableCash)} />
        <MetricCard
          label="持仓市值"
          value={formatCurrency(dashboard.metrics.positionMarketValue)}
        />
        <MetricCard
          label="当日收益"
          value={formatCurrency(dashboard.metrics.dailyPnl)}
          accent={dashboard.metrics.dailyPnl}
        />
        <MetricCard
          label="累计收益"
          value={formatCurrency(dashboard.metrics.cumulativePnl)}
          accent={dashboard.metrics.cumulativePnl}
        />
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
        {activeTab === "positions" && (
          <PositionsTab
            rows={positions}
            pendingOrders={pendingOrders}
            currentTradeDate={dashboard.tradeDate}
            deletingOrderId={deletingPendingOrderId}
            onDeleteOrder={handleDeletePendingOrder}
          />
        )}
        {activeTab === "history" && (
          <HistoryTab
            rows={history}
            extraDates={[
              ...calendar.map((row) => row.date),
              ...(dashboard.marketStatus === "weekend" ? [] : [dashboard.tradeDate]),
            ]}
          />
        )}
        {activeTab === "pnl" && (
          <PnlTab
            rows={calendar}
            selectedDate={selectedDate}
            onSelectDate={setSelectedDate}
            details={dailyDetail}
            trades={history}
          />
        )}
        {activeTab === "import" && (
          <ImportTab
            key={`${activeUserId}-${dashboard.suggestedImportTradeDate}`}
            marketStatus={dashboard.marketStatus}
            pendingOrders={pendingOrders}
            targetTradeDate={dashboard.suggestedImportTradeDate}
            onImportCommitted={() => loadCoreData(selectedDate)}
          />
        )}
      </main>
    </div>
  );
}

function CreateUserModal({
  name,
  cash,
  errorMessage,
  loading,
  inputRef,
  onNameChange,
  onCashChange,
  onCancel,
  onSubmit,
}: {
  name: string;
  cash: string;
  errorMessage: string;
  loading: boolean;
  inputRef: { current: HTMLInputElement | null };
  onNameChange: (value: string) => void;
  onCashChange: (value: string) => void;
  onCancel: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  return (
    <div className="modal-backdrop" onClick={loading ? undefined : onCancel}>
      <div className="modal-card create-user-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h3>新建账户</h3>
            <p>创建一个独立账户，并设置它的起始资金。</p>
          </div>
          <button
            type="button"
            className="modal-close-button"
            onClick={onCancel}
            disabled={loading}
            aria-label="关闭新建账户弹窗"
          >
            关闭
          </button>
        </div>
        <form className="modal-form" noValidate onSubmit={(event) => void onSubmit(event)}>
          <label className="modal-field">
            <span>用户名称</span>
            <input
              ref={inputRef}
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
              placeholder="例如：Alice"
              disabled={loading}
            />
          </label>
          <label className="modal-field">
            <span>初始资金</span>
            <input
              type="number"
              min="0.01"
              step="0.01"
              inputMode="decimal"
              value={cash}
              onChange={(event) => onCashChange(event.target.value)}
              placeholder="500000"
              disabled={loading}
            />
          </label>
          {errorMessage ? <div className="modal-error">{errorMessage}</div> : null}
          <div className="modal-actions">
            <button
              type="button"
              className="user-secondary-button"
              onClick={onCancel}
              disabled={loading}
            >
              取消
            </button>
            <button type="submit" className="user-primary-button" disabled={loading}>
              {loading ? "创建中..." : "确认创建"}
            </button>
          </div>
        </form>
      </div>
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

function PositionsTab({
  rows,
  pendingOrders,
  currentTradeDate,
  deletingOrderId,
  onDeleteOrder,
}: {
  rows: PositionRow[];
  pendingOrders: PendingOrderRow[];
  currentTradeDate: string;
  deletingOrderId: string | null;
  onDeleteOrder: (order: PendingOrderRow) => Promise<void> | void;
}) {
  const activePendingOrders = useMemo(
    () =>
      [...pendingOrders]
        .filter((row) => isPendingOrderEffectiveToday(row, currentTradeDate))
        .sort(
          (a, b) =>
            b.tradeDate.localeCompare(a.tradeDate) || b.updatedAt.localeCompare(a.updatedAt),
        ),
    [currentTradeDate, pendingOrders],
  );

  return (
    <section className="positions-layout">
      <DataTable
        headers={[
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
          "浮盈亏",
          "收益率",
        ]}
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

function HistoryTab({ rows, extraDates }: { rows: HistoryRow[]; extraDates: string[] }) {
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

function PnlTab({
  rows,
  selectedDate,
  onSelectDate,
  details,
  trades,
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
    () => trades.filter((t) => t.time.startsWith(selectedDate)),
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
                  dayTrades.map((t) => (
                    <div key={t.id} className="daily-detail-row trades-row">
                      <span className="detail-cell">{t.time.slice(11, 19)}</span>
                      <span className="detail-cell detail-cell-symbol">{t.symbol}</span>
                      <span className="detail-cell detail-cell-name">{t.name}</span>
                      <span className={`detail-cell ${t.side === "BUY" ? "up" : "down"}`}>
                        {t.side === "BUY" ? "买入" : "卖出"}
                      </span>
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
  pendingOrders,
  targetTradeDate,
  onImportCommitted,
}: {
  marketStatus: MarketStatus;
  pendingOrders: PendingOrderRow[];
  targetTradeDate: string;
  onImportCommitted: () => Promise<unknown> | unknown;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);
  const [clearingDraft, setClearingDraft] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [validatingAll, setValidatingAll] = useState(false);
  const [submittingImport, setSubmittingImport] = useState(false);
  const [deletingOrderId, setDeletingOrderId] = useState<string | null>(null);
  const [restoringDraft, setRestoringDraft] = useState(false);
  const [orderFilter, setOrderFilter] = useState<ImportOrderFilter>(
    marketStatus === "closed" ? "all" : "active",
  );
  const [draftSavedAt, setDraftSavedAt] = useState<string>("");
  const [workflowFeedback, setWorkflowFeedback] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);
  const [isDraftDirty, setIsDraftDirty] = useState(false);
  const [draftFileName, setDraftFileName] = useState<string>("");
  const [validationBatchIds, setValidationBatchIds] = useState<Record<string, string>>({});
  const previousMarketStatusRef = useRef<MarketStatus | null>(null);
  const [manualRows, setManualRows] = useState<ManualInputRow[]>([
    createManualInputRow({ tradeDate: targetTradeDate }),
  ]);
  const isImportWindowOpen = marketStatus !== "weekend";

  const touchedManualRows = useMemo(() => manualRows.filter(isManualRowTouched), [manualRows]);
  const hasIncompleteManualRows = touchedManualRows.some((row) => !isManualRowComplete(row));
  const manualRowsByTradeDate = useMemo(
    () => groupManualRowsByTradeDate(touchedManualRows),
    [touchedManualRows],
  );
  const manualTradeDates = useMemo(
    () => manualRowsByTradeDate.map((group) => group.tradeDate).filter((value) => value !== ""),
    [manualRowsByTradeDate],
  );
  const validationSummary = useMemo(
    () => importValidationSummary(touchedManualRows),
    [touchedManualRows],
  );
  const previewValidCount = validationSummary.VALID;
  const previewWarningCount = validationSummary.WARNING;
  const previewErrorCount = validationSummary.ERROR;
  const canSaveManualDraft = manualTradeDates.length > 0 && !hasIncompleteManualRows;
  const canValidateAll = canSaveManualDraft;
  const canSubmitImport =
    manualTradeDates.length > 0 &&
    !hasIncompleteManualRows &&
    previewErrorCount === 0 &&
    manualTradeDates.every((tradeDate) => validationBatchIds[tradeDate]);
  const isWorking =
    uploading ||
    downloadingTemplate ||
    clearingDraft ||
    savingDraft ||
    validatingAll ||
    submittingImport ||
    deletingOrderId !== null ||
    restoringDraft;
  const importOrders = useMemo(
    () =>
      [...pendingOrders]
        .filter((row) => matchesImportOrderFilter(row, orderFilter))
        .sort(
          (a, b) =>
            b.tradeDate.localeCompare(a.tradeDate) || b.updatedAt.localeCompare(a.updatedAt),
        ),
    [orderFilter, pendingOrders],
  );

  useEffect(() => {
    setManualRows((currentRows) =>
      currentRows.map((row) =>
        isManualRowTouched(row) ? row : { ...row, tradeDate: targetTradeDate },
      ),
    );
  }, [targetTradeDate]);

  useEffect(() => {
    if (
      previousMarketStatusRef.current !== "closed" &&
      marketStatus === "closed" &&
      orderFilter === "active"
    ) {
      setOrderFilter("all");
    }
    previousMarketStatusRef.current = marketStatus;
  }, [marketStatus, orderFilter]);

  useEffect(() => {
    if (!workflowFeedback) {
      return undefined;
    }

    const timerId = window.setTimeout(() => {
      setWorkflowFeedback(null);
    }, WORKFLOW_FEEDBACK_DURATION_MS);

    return () => {
      window.clearTimeout(timerId);
    };
  }, [workflowFeedback]);

  useEffect(() => {
    let cancelled = false;

    async function restoreLatestDraft() {
      setRestoringDraft(true);
      setWorkflowFeedback(null);

      try {
        const response = await api.getLatestImports();
        if (cancelled) {
          return;
        }

        const latestDraftByTradeDate = new Map<string, LatestImportBatch>();
        for (const batch of response.rows) {
          if (batch.mode !== "DRAFT" || batch.status !== "VALIDATED") {
            continue;
          }
          if (!latestDraftByTradeDate.has(batch.targetTradeDate)) {
            latestDraftByTradeDate.set(batch.targetTradeDate, batch);
          }
        }

        const latestDrafts = Array.from(latestDraftByTradeDate.values()).sort((a, b) =>
          a.targetTradeDate.localeCompare(b.targetTradeDate),
        );

        if (latestDrafts.length === 0) {
          setManualRows([createManualInputRow({ tradeDate: targetTradeDate })]);
          setDraftSavedAt("");
          setDraftFileName("");
          setValidationBatchIds({});
          setIsDraftDirty(false);
          return;
        }

        setManualRows(latestDrafts.flatMap((batch) => createManualRowsFromBatch(batch)));
        setDraftSavedAt(formatDraftSavedAt(latestDrafts[0].createdAt));
        setDraftFileName(latestDrafts.length === 1 ? (latestDrafts[0].fileName ?? "") : "");
        setValidationBatchIds(
          Object.fromEntries(latestDrafts.map((batch) => [batch.targetTradeDate, batch.id])),
        );
        setIsDraftDirty(false);
      } catch (error) {
        if (!cancelled) {
          setWorkflowFeedback({
            tone: "error",
            text: error instanceof Error ? error.message : "加载最近草稿失败",
          });
        }
      } finally {
        if (!cancelled) {
          setRestoringDraft(false);
        }
      }
    }

    void restoreLatestDraft();

    return () => {
      cancelled = true;
    };
  }, [targetTradeDate]);

  function resetValidationState() {
    setValidationBatchIds({});
    setManualRows((currentRows) => currentRows.map(clearManualRowValidation));
  }

  function markDraftDirty() {
    setIsDraftDirty(true);
    setWorkflowFeedback(null);
    resetValidationState();
  }

  function syncRowsWithPreviewRows(previewByRowId: Map<string, ImportPreviewRow>) {
    setManualRows((currentRows) => {
      return currentRows.map((row) => {
        if (!isManualRowTouched(row)) {
          return clearManualRowValidation(row);
        }

        const preview = previewByRowId.get(row.id);

        if (!preview) {
          return clearManualRowValidation(row);
        }

        return {
          ...row,
          tradeDate: preview.tradeDate,
          symbol: preview.symbol,
          side: preview.side,
          validity: preview.validity,
          price: String(preview.price),
          lots: String(preview.lots),
          validationStatus: preview.validationStatus,
          validationMessage: preview.validationMessage,
        };
      });
    });
  }

  function applyValidatedDrafts({
    batches,
    successText,
    fileName,
    savedAt,
  }: {
    batches: Array<{
      tradeDate: string;
      rowIds: string[];
      batchId: string;
      rows: ImportPreviewRow[];
    }>;
    successText: string;
    fileName?: string;
    savedAt?: string;
  }) {
    const previewByRowId = new Map<string, ImportPreviewRow>();
    for (const batch of batches) {
      batch.rowIds.forEach((rowId, index) => {
        const preview = batch.rows[index];
        if (preview) {
          previewByRowId.set(rowId, preview);
        }
      });
    }

    syncRowsWithPreviewRows(previewByRowId);
    setValidationBatchIds(
      Object.fromEntries(batches.map((batch) => [batch.tradeDate, batch.batchId])),
    );
    setDraftSavedAt(savedAt ?? currentDraftSavedAt());
    setDraftFileName(fileName ?? "");
    setIsDraftDirty(false);
    setWorkflowFeedback({ tone: "success", text: successText });
  }

  function updateManualRow<K extends Exclude<keyof ManualInputRow, "id">>(
    id: string,
    key: K,
    value: ManualInputRow[K],
  ) {
    markDraftDirty();
    setManualRows((currentRows) =>
      currentRows.map((row) => (row.id === id ? { ...row, [key]: value } : row)),
    );
  }

  function addManualRow(afterId?: string) {
    markDraftDirty();
    setManualRows((currentRows) => {
      const nextRow = createManualInputRow({
        tradeDate: nextManualRowTradeDate(currentRows, targetTradeDate, afterId),
      });

      if (!afterId) {
        return [...currentRows, nextRow];
      }

      const insertIndex = currentRows.findIndex((row) => row.id === afterId);

      if (insertIndex < 0) {
        return [...currentRows, nextRow];
      }

      return [
        ...currentRows.slice(0, insertIndex + 1),
        nextRow,
        ...currentRows.slice(insertIndex + 1),
      ];
    });
  }

  function removeManualRow(id: string) {
    markDraftDirty();
    setManualRows((currentRows) => {
      if (currentRows.length === 1) {
        return [createManualInputRow({ tradeDate: targetTradeDate })];
      }

      return currentRows.filter((row) => row.id !== id);
    });
  }

  function resetManualRowsState() {
    setWorkflowFeedback(null);
    setIsDraftDirty(false);
    setDraftSavedAt("");
    setDraftFileName("");
    setValidationBatchIds({});
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    setManualRows([createManualInputRow({ tradeDate: targetTradeDate })]);
  }

  async function handleClearManualRows() {
    setWorkflowFeedback(null);
    setClearingDraft(true);

    try {
      const tradeDatesToClear = Array.from(
        new Set(
          [
            ...Object.keys(validationBatchIds),
            ...touchedManualRows.map((row) => row.tradeDate.trim()),
          ].filter((value) => value !== ""),
        ),
      );
      const dates = tradeDatesToClear.length > 0 ? tradeDatesToClear : [targetTradeDate];
      await Promise.all(dates.map((tradeDate) => api.clearImportDrafts(tradeDate)));
      resetManualRowsState();
    } catch (error) {
      setWorkflowFeedback({
        tone: "error",
        text: error instanceof Error ? error.message : "清空草稿失败",
      });
    } finally {
      setClearingDraft(false);
    }
  }

  async function handleUpload(file: File) {
    setWorkflowFeedback(null);
    setUploading(true);

    try {
      const response = await api.uploadImportFile({
        file,
        mode: "DRAFT",
      });
      setManualRows(createManualRowsFromPreview(response.rows, targetTradeDate));
      setDraftSavedAt(currentDraftSavedAt());
      setDraftFileName(response.fileName ?? file.name);
      setValidationBatchIds(response.batchIds);
      setIsDraftDirty(false);
      setWorkflowFeedback({
        tone: "success",
        text: `文件已导入，共 ${response.rows.length} 条，已按挂单时间完成校验。`,
      });
    } catch (error) {
      setWorkflowFeedback({
        tone: "error",
        text: error instanceof Error ? error.message : "上传失败",
      });
    } finally {
      setUploading(false);
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFile = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (!nextFile) {
      return;
    }
    void handleUpload(nextFile);
  }

  async function handleSaveDraft() {
    if (!canSaveManualDraft) {
      return;
    }

    setWorkflowFeedback(null);
    setSavingDraft(true);

    try {
      const responses = await Promise.all(
        manualRowsByTradeDate.map(async (group) => {
          const response = await api.previewImports({
            targetTradeDate: group.tradeDate,
            mode: "DRAFT",
            sourceType: "MANUAL",
            fileName: draftFileName || undefined,
            rows: group.items.map((item) => item.payload),
          });
          return {
            tradeDate: group.tradeDate,
            rowIds: group.items.map((item) => item.rowId),
            batchId: response.batchId,
            rows: response.rows,
          };
        }),
      );
      applyValidatedDrafts({
        batches: responses,
        fileName: draftFileName || undefined,
        successText: "草稿已保存，并同步了最新校验结果。",
      });
    } catch (error) {
      setWorkflowFeedback({
        tone: "error",
        text: error instanceof Error ? error.message : "保存草稿失败",
      });
    } finally {
      setSavingDraft(false);
    }
  }

  async function handleTemplateDownload() {
    setDownloadingTemplate(true);

    try {
      const templateTradeDate =
        touchedManualRows[0]?.tradeDate?.trim() ||
        manualRows[0]?.tradeDate?.trim() ||
        targetTradeDate;
      const blob = await api.downloadImportTemplate(templateTradeDate);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `import-template-${templateTradeDate}.xlsx`;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setWorkflowFeedback({
        tone: "error",
        text: error instanceof Error ? error.message : "下载模板失败",
      });
    } finally {
      setDownloadingTemplate(false);
    }
  }

  async function handleValidateAll() {
    if (!canValidateAll) {
      return;
    }

    setWorkflowFeedback(null);
    setValidatingAll(true);

    try {
      const responses = await Promise.all(
        manualRowsByTradeDate.map(async (group) => {
          const response = await api.previewImports({
            targetTradeDate: group.tradeDate,
            mode: "DRAFT",
            sourceType: "MANUAL",
            fileName: draftFileName || undefined,
            rows: group.items.map((item) => item.payload),
          });
          return {
            tradeDate: group.tradeDate,
            rowIds: group.items.map((item) => item.rowId),
            batchId: response.batchId,
            rows: response.rows,
          };
        }),
      );
      applyValidatedDrafts({
        batches: responses,
        fileName: draftFileName || undefined,
        successText: "已完成校验，可直接在当前表格继续修改。",
      });
    } catch (error) {
      setWorkflowFeedback({
        tone: "error",
        text: error instanceof Error ? error.message : "校验失败",
      });
    } finally {
      setValidatingAll(false);
    }
  }

  async function handleImportSubmit() {
    if (!canSubmitImport || !isImportWindowOpen) {
      return;
    }

    setWorkflowFeedback(null);
    setSubmittingImport(true);

    let importedCount = 0;
    try {
      for (const tradeDate of manualTradeDates) {
        const batchId = validationBatchIds[tradeDate];
        if (!batchId) {
          continue;
        }
        const response = await api.commitImports({
          batchId,
          mode: "APPEND",
        });
        importedCount += response.importedCount;
      }
      resetManualRowsState();
      setWorkflowFeedback({
        tone: "success",
        text: `已提交 ${importedCount} 条，已生成委托记录，可在下方查看状态。`,
      });
      await onImportCommitted();
    } catch (error) {
      const message = error instanceof Error ? error.message : "提交导入失败";
      if (message.includes("请重新校验")) {
        resetValidationState();
      }
      setWorkflowFeedback({
        tone: "error",
        text: importedCount > 0 ? `已提交 ${importedCount} 条，剩余提交失败：${message}` : message,
      });
    } finally {
      setSubmittingImport(false);
    }
  }

  async function handleDeleteOrder(order: PendingOrderRow) {
    if (!order.canDelete || deletingOrderId) {
      return;
    }

    setDeletingOrderId(order.id);

    try {
      await api.deleteOrder(order.id);
      await onImportCommitted();
    } catch {
      // Keep the operation-entry feedback area focused on import workflow actions.
    } finally {
      setDeletingOrderId(null);
    }
  }

  return (
    <section className="import-layout">
      <article className="input-card import-workflow-card">
        <div className="input-card-head import-toolbar-head">
          <div className="import-section-copy">
            <h3>操作录入</h3>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
          <div className="button-row import-toolbar-actions">
            <button
              type="button"
              onClick={() => void handleTemplateDownload()}
              disabled={isWorking}
            >
              {downloadingTemplate ? "下载中..." : "下载模板"}
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isWorking}
            >
              {uploading ? "导入中..." : "文件导入"}
            </button>
          </div>
        </div>
        {workflowFeedback ? (
          <div
            className={
              workflowFeedback.tone === "error"
                ? "import-feedback import-feedback-error"
                : "import-feedback import-feedback-success"
            }
          >
            {workflowFeedback.text}
          </div>
        ) : null}
        <div className="manual-grid-shell">
          <div className="manual-grid-head">
            <div className="import-draft-meta">
              <span className="input-card-tag">待处理 {touchedManualRows.length} 条</span>
              <span className="input-card-tag import-summary-tag import-summary-tag-valid">
                通过 {previewValidCount}
              </span>
              <span className="input-card-tag import-summary-tag import-summary-tag-warning">
                警告 {previewWarningCount}
              </span>
              <span className="input-card-tag import-summary-tag import-summary-tag-error">
                错误 {previewErrorCount}
              </span>
              {draftSavedAt ? (
                <span className="input-card-tag">最近保存 {draftSavedAt}</span>
              ) : null}
              {restoringDraft ? <span className="input-card-tag">正在恢复草稿...</span> : null}
            </div>
            <button
              type="button"
              className="manual-row-icon-button manual-add-button"
              onClick={() => addManualRow()}
              disabled={isWorking}
              aria-label="新增一行"
              title="新增一行"
            >
              +
            </button>
          </div>
          <div className="manual-grid-table" role="table" aria-label="导入编辑表格">
            <div className="manual-grid-header manual-grid-header-expanded" role="row">
              <span>行号</span>
              <span>股票代码</span>
              <span>方向</span>
              <span>挂单时间</span>
              <span>挂单方式</span>
              <span>委托价</span>
              <span>手数</span>
              <span>校验结果</span>
              <span>操作</span>
            </div>
            <div className="manual-grid-body">
              {manualRows.map((row, index) => {
                const validation = importRowValidationState(row, isDraftDirty);

                return (
                  <div
                    key={row.id}
                    className={`manual-grid-body-row manual-grid-body-row-${
                      row.validationStatus?.toLowerCase() ?? "pending"
                    }`}
                    role="row"
                  >
                    <div className="manual-grid-row-fields manual-grid-row-fields-expanded">
                      <span className="manual-row-number">{index + 1}</span>
                      <label className="manual-field">
                        <span className="sr-only">第 {index + 1} 行股票代码</span>
                        <input
                          value={row.symbol}
                          disabled={isWorking}
                          onChange={(event) =>
                            updateManualRow(row.id, "symbol", event.target.value.toUpperCase())
                          }
                          placeholder="如 600519"
                        />
                      </label>
                      <label className="manual-field">
                        <span className="sr-only">第 {index + 1} 行方向</span>
                        <select
                          value={row.side}
                          disabled={isWorking}
                          onChange={(event) =>
                            updateManualRow(
                              row.id,
                              "side",
                              event.target.value as ManualImportRowInput["side"],
                            )
                          }
                        >
                          {MANUAL_SIDE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="manual-field">
                        <span className="sr-only">第 {index + 1} 行挂单时间</span>
                        <input
                          type="date"
                          value={row.tradeDate}
                          disabled={isWorking}
                          onChange={(event) =>
                            updateManualRow(row.id, "tradeDate", event.target.value)
                          }
                        />
                      </label>
                      <label className="manual-field">
                        <span className="sr-only">第 {index + 1} 行挂单方式</span>
                        <select
                          value={row.validity}
                          disabled={isWorking}
                          onChange={(event) =>
                            updateManualRow(
                              row.id,
                              "validity",
                              event.target.value as ManualImportRowInput["validity"],
                            )
                          }
                        >
                          {MANUAL_VALIDITY_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
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
                          disabled={isWorking}
                          onChange={(event) => updateManualRow(row.id, "price", event.target.value)}
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
                          disabled={isWorking}
                          onChange={(event) => updateManualRow(row.id, "lots", event.target.value)}
                          placeholder="1"
                        />
                      </label>
                      <div className="manual-validation-cell">
                        <span className={validation.badgeClassName}>{validation.label}</span>
                        <div className="validation-note">{validation.message}</div>
                      </div>
                      <div className="manual-row-action-cell">
                        <button
                          type="button"
                          className="manual-row-icon-button manual-row-icon-button-danger"
                          onClick={() => removeManualRow(row.id)}
                          disabled={isWorking}
                          aria-label={`删除第 ${index + 1} 行`}
                          title="删除当前行"
                        >
                          -
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
        <div className="import-submit-actions">
          <div className="button-row footer-actions">
            <button type="button" onClick={() => void handleClearManualRows()} disabled={isWorking}>
              {clearingDraft ? "清空中..." : "清空草稿"}
            </button>
            <button
              type="button"
              onClick={() => void handleSaveDraft()}
              disabled={isWorking || !canSaveManualDraft}
            >
              {savingDraft ? "保存中..." : "保存草稿"}
            </button>
            <button
              type="button"
              onClick={() => void handleValidateAll()}
              disabled={isWorking || !canValidateAll}
            >
              {validatingAll ? "校验中..." : "校验全部"}
            </button>
            <button
              type="button"
              onClick={() => void handleImportSubmit()}
              disabled={isWorking || !canSubmitImport || !isImportWindowOpen}
            >
              {submittingImport ? "提交中..." : "提交导入"}
            </button>
          </div>
        </div>
      </article>

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
                    orderFilter === option.value
                      ? "history-mode-button active"
                      : "history-mode-button"
                  }
                  onClick={() => setOrderFilter(option.value)}
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
                          onClick={() => void handleDeleteOrder(row)}
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
                  <td colSpan={10} className="empty-state">
                    暂无委托记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </article>
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
