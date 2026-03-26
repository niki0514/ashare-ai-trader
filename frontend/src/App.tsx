import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, getActiveUserId as readActiveUserId, setActiveUserId as persistActiveUserId } from "./api";
import { ClosedPositionsTab } from "./components/ClosedPositionsTab";
import { CreateUserModal } from "./components/CreateUserModal";
import { HistoryTab } from "./components/HistoryTab";
import { ImportTab } from "./components/ImportTab";
import { MetricCard } from "./components/MetricCard";
import { PnlTab } from "./components/PnlTab";
import { PositionsTab } from "./components/PositionsTab";
import { isNonTradingMarketStatus } from "./orderHelpers";
import type {
  CalendarDay,
  ClosedPositionRow,
  DailyPnlDetailRow,
  DashboardResponse,
  HistoryRow,
  PendingOrderRow,
  PositionRow,
  UserSummary,
} from "./types";
import { formatCurrency, formatPercent, statusLabel } from "./utils";

type TabKey = "positions" | "closed" | "history" | "pnl" | "import";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "positions", label: "持仓明细" },
  { key: "closed", label: "已清仓" },
  { key: "history", label: "历史流水" },
  { key: "pnl", label: "每日收益" },
  { key: "import", label: "操作录入" },
];
const CORE_DATA_POLL_MS = 3000;
const DEFAULT_NEW_USER_CASH = "500000";

export default function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("positions");
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [activeUserId, setActiveUserIdState] = useState<string>(readActiveUserId());
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [closedPositions, setClosedPositions] = useState<ClosedPositionRow[]>([]);
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
    setClosedPositions([]);
    setPendingOrders([]);
    setHistory([]);
    setCalendar([]);
    setDailyDetail([]);
  }

  async function loadCoreData(currentSelectedDate: string) {
    const [
      dashboardRes,
      positionsRes,
      closedPositionsRes,
      pendingOrdersRes,
      historyRes,
      calendarRes,
      dailyRes,
    ] =
      await Promise.all([
        api.getDashboard(),
        api.getPositions(),
        api.getClosedPositions(),
        api.getPendingOrders(),
        api.getHistory(),
        api.getCalendar(),
        api.getDailyPnlDetail(currentSelectedDate),
      ]);

    setDashboard(dashboardRes);
    setPositions(positionsRes.rows);
    setClosedPositions(closedPositionsRes.rows);
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
        {activeTab === "closed" && <ClosedPositionsTab rows={closedPositions} />}
        {activeTab === "history" && (
          <HistoryTab
            rows={history}
            extraDates={[
              ...calendar.map((row) => row.date),
              ...(isNonTradingMarketStatus(dashboard.marketStatus) ? [] : [dashboard.tradeDate]),
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
