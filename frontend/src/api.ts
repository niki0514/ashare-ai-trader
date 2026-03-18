import type {
  CalendarDay,
  DailyPnlDetailRow,
  DashboardResponse,
  HistoryRow,
  ImportCommitResponse,
  ImportPreviewResponse,
  PendingOrderRow,
  PositionRow,
  QuoteResponse
} from "./types";

const API_BASE = "http://localhost:3001/api";

export type ImportMode = "DRAFT" | "OVERWRITE" | "APPEND";

export type ImportSourceType = "MANUAL" | "XLSX" | "CSV";

export type ManualImportRowInput = {
  symbol: string;
  side: "BUY" | "SELL";
  price: number;
  lots: number;
  validity: "DAY" | "GTC";
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);

  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers
    });
  } catch {
    throw new Error("无法连接后端服务，请确认 backend 已启动在 http://localhost:3001");
  }

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new Error("无法连接后端服务，请确认 backend 已启动在 http://localhost:3001");
  }

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return response.blob();
}

export const api = {
  getDashboard: () => request<DashboardResponse>("/dashboard"),
  getPositions: () => request<{ rows: PositionRow[] }>("/positions"),
  getPendingOrders: () => request<{ rows: PendingOrderRow[] }>("/orders/pending"),
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
  uploadImportFile: (payload: { file: File; targetTradeDate: string; mode?: ImportMode }) => {
    const formData = new FormData();
    formData.append("file", payload.file);
    formData.append("targetTradeDate", payload.targetTradeDate);
    formData.append("mode", payload.mode ?? "DRAFT");

    return request<ImportPreviewResponse>("/imports/upload", {
      method: "POST",
      body: formData
    });
  },
  downloadImportTemplate: (targetTradeDate?: string) =>
    requestBlob(`/imports/template${targetTradeDate ? `?targetTradeDate=${encodeURIComponent(targetTradeDate)}` : ""}`),
  commitImports: (payload: { batchId: string; mode: ImportMode }) =>
    request<ImportCommitResponse>("/imports/commit", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  getQuotes: (symbols: string[]) => request<QuoteResponse>(`/quotes?symbols=${symbols.join(",")}`)
};
