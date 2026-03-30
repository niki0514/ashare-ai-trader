import type {
  CalendarDay,
  ClosedPositionRow,
  DailyPnlDetailRow,
  DashboardResponse,
  HistoryRow,
  ImportCommitResponse,
  ImportPreviewResponse,
  ImportUploadResponse,
  LatestImportBatch,
  PendingOrderRow,
  PositionRow,
  ResolvedSymbolRow,
  UserSummary,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";
const DEFAULT_REQUEST_TIMEOUT_MS = 15000;
const FILE_REQUEST_TIMEOUT_MS = 30000;
const ACTIVE_USER_STORAGE_KEY = "ashare-active-user-id";

export type ImportMode = "DRAFT" | "OVERWRITE" | "APPEND";

export type ImportSourceType = "MANUAL" | "XLSX" | "CSV";

export type ManualImportRowInput = {
  symbol: string;
  side: "BUY" | "SELL";
  price: number;
  lots: number;
  validity: "DAY" | "GTC";
};

function readStoredActiveUserId(): string {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(ACTIVE_USER_STORAGE_KEY) ?? "";
}

let activeUserId = readStoredActiveUserId();

export function getActiveUserId() {
  return activeUserId;
}

export function setActiveUserId(userId: string) {
  activeUserId = userId.trim();
  if (typeof window !== "undefined") {
    if (activeUserId === "") {
      window.localStorage.removeItem(ACTIVE_USER_STORAGE_KEY);
    } else {
      window.localStorage.setItem(ACTIVE_USER_STORAGE_KEY, activeUserId);
    }
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";

  try {
    if (contentType.includes("application/json")) {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string" && payload.detail.trim() !== "") {
        return payload.detail;
      }
    } else {
      const text = await response.text();
      if (text.trim() !== "") {
        return text;
      }
    }
  } catch {
    // ignore parse errors and fall back to generic message
  }

  return `API request failed: ${response.status}`;
}

async function performFetch(
  path: string,
  init?: RequestInit,
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时，请确认 backend 服务正常后重试");
    }

    throw new Error("无法连接后端服务，请确认 backend 已启动，且前端代理配置正确");
  } finally {
    window.clearTimeout(timeoutId);
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options?: { timeoutMs?: number },
): Promise<T> {
  const headers = new Headers(init?.headers);

  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const userId = getActiveUserId();
  if (userId !== "" && !headers.has("x-user-id")) {
    headers.set("x-user-id", getActiveUserId());
  }

  const response = await performFetch(
    path,
    {
      ...init,
      headers,
    },
    options?.timeoutMs,
  );

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json() as Promise<T>;
}

async function requestBlob(path: string, init?: RequestInit, options?: { timeoutMs?: number }): Promise<Blob> {
  const response = await performFetch(path, init, options?.timeoutMs);

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.blob();
}

export const api = {
  getUsers: () => request<{ rows: UserSummary[] }>("/users"),
  createUser: (payload: { name: string; initialCash: number }) =>
    request<UserSummary>("/users", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  getDashboard: () => request<DashboardResponse>("/dashboard"),
  getPositions: () => request<{ rows: PositionRow[] }>("/positions"),
  getClosedPositions: () => request<{ rows: ClosedPositionRow[] }>("/positions/closed"),
  getPendingOrders: () => request<{ rows: PendingOrderRow[] }>("/orders/pending"),
  deleteOrder: (orderId: string) =>
    request<{ deletedId: string }>(`/orders/${encodeURIComponent(orderId)}`, {
      method: "DELETE",
    }),
  getHistory: () => request<{ rows: HistoryRow[] }>("/history"),
  getCalendar: () => request<{ rows: CalendarDay[] }>("/pnl/calendar"),
  getDailyPnlDetail: (date: string) => request<{ date: string; rows: DailyPnlDetailRow[] }>(`/pnl/daily/${date}`),
  previewImports: (payload: {
    targetTradeDate: string;
    mode?: ImportMode;
    sourceType?: ImportSourceType;
    fileName?: string;
    rows: ManualImportRowInput[];
  }) =>
    request<ImportPreviewResponse>("/imports/preview", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  resolveSymbols: (payload: { targetTradeDate: string; symbols: string[] }) =>
    request<{ rows: ResolvedSymbolRow[] }>("/symbols/resolve", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadImportFile: (payload: { file: File; mode?: ImportMode }) => {
    const formData = new FormData();
    formData.append("file", payload.file);
    formData.append("mode", payload.mode ?? "DRAFT");

    return request<ImportUploadResponse>("/imports/upload", {
      method: "POST",
      body: formData
    }, {
      timeoutMs: FILE_REQUEST_TIMEOUT_MS,
    });
  },
  downloadImportTemplate: (targetTradeDate?: string) =>
    requestBlob(
      `/imports/template${targetTradeDate ? `?targetTradeDate=${encodeURIComponent(targetTradeDate)}` : ""}`,
      undefined,
      {
        timeoutMs: FILE_REQUEST_TIMEOUT_MS,
      },
    ),
  commitImports: (payload: {
    batchId: string;
    mode: ImportMode;
    confirmWarnings?: boolean;
    confirmationToken?: string;
  }) =>
    request<ImportCommitResponse>("/imports/commit", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  getLatestImports: (tradeDate?: string) =>
    request<{ rows: LatestImportBatch[] }>(
      `/imports/latest${tradeDate ? `?tradeDate=${encodeURIComponent(tradeDate)}` : ""}`,
    ),
  clearImportDrafts: (tradeDate: string) =>
    request<{ deletedCount: number }>(
      `/imports/draft?tradeDate=${encodeURIComponent(tradeDate)}`,
      {
        method: "DELETE",
      },
    ),
};
