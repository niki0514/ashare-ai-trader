import type { ManualImportRowInput } from "./api";
import type { ImportPreviewRow, LatestImportBatch } from "./types";

export type ManualNameStatus = "idle" | "resolving" | "resolved" | "unresolved";

export type ManualInputRow = {
  id: string;
  symbol: string;
  name: string;
  nameStatus: ManualNameStatus;
  side: ManualImportRowInput["side"];
  tradeDate: string;
  validity: ManualImportRowInput["validity"];
  price: string;
  lots: string;
  validationStatus: ImportPreviewRow["validationStatus"] | null;
  validationMessage: string;
};

export const MANUAL_SIDE_OPTIONS: Array<{
  value: ManualImportRowInput["side"];
  label: string;
}> = [
  { value: "BUY", label: "买入" },
  { value: "SELL", label: "卖出" },
];

export const MANUAL_VALIDITY_OPTIONS: Array<{
  value: ManualImportRowInput["validity"];
  label: string;
}> = [
  { value: "DAY", label: "当日挂单" },
  { value: "GTC", label: "持续挂单" },
];

function manualNameStatusForValue(name: string, symbol: string): ManualNameStatus {
  const normalizedName = name.trim();
  const normalizedSymbol = symbol.trim().toUpperCase();

  if (normalizedName !== "" && normalizedName !== normalizedSymbol) {
    return "resolved";
  }

  return "idle";
}

export function createManualInputRow(
  seed: Partial<
    ManualImportRowInput & {
      name: string;
      nameStatus: ManualNameStatus;
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
    name: seed.name ?? "",
    nameStatus: seed.nameStatus ?? manualNameStatusForValue(seed.name ?? "", seed.symbol ?? ""),
    side: seed.side ?? "BUY",
    tradeDate: seed.tradeDate ?? "",
    validity: seed.validity ?? "DAY",
    price: seed.price === undefined ? "" : String(seed.price),
    lots: seed.lots === undefined ? "1" : String(seed.lots),
    validationStatus: seed.validationStatus ?? null,
    validationMessage: seed.validationMessage ?? "",
  };
}

export function createManualRowsFromPreview(
  rows: ImportPreviewRow[],
  fallbackTradeDate: string,
): ManualInputRow[] {
  if (rows.length === 0) {
    return [createManualInputRow({ tradeDate: fallbackTradeDate })];
  }

  return rows.map((row) =>
    createManualInputRow({
      symbol: row.symbol,
      name: row.name,
      nameStatus: manualNameStatusForValue(row.name, row.symbol),
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

export function createManualRowsFromBatch(batch: LatestImportBatch): ManualInputRow[] {
  if (batch.items.length === 0) {
    return [createManualInputRow({ tradeDate: batch.targetTradeDate })];
  }

  return batch.items.map((item) =>
    createManualInputRow({
      symbol: item.symbol,
      name: item.name,
      nameStatus: manualNameStatusForValue(item.name, item.symbol),
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

export function clearManualRowValidation(row: ManualInputRow): ManualInputRow {
  if (row.validationStatus === null && row.validationMessage === "") {
    return row;
  }

  return {
    ...row,
    validationStatus: null,
    validationMessage: "",
  };
}

export function isManualRowTouched(row: ManualInputRow) {
  return (
    row.symbol.trim() !== "" ||
    row.price.trim() !== "" ||
    row.lots.trim() !== "1" ||
    row.side !== "BUY" ||
    row.validity !== "DAY"
  );
}

export function parseManualNumber(value: string) {
  const trimmed = value.trim();
  return trimmed === "" ? Number.NaN : Number(trimmed);
}

export function isManualRowComplete(row: ManualInputRow) {
  return (
    row.tradeDate.trim() !== "" &&
    row.symbol.trim() !== "" &&
    parseManualNumber(row.price) > 0 &&
    parseManualNumber(row.lots) > 0
  );
}

export function importValidationSummary(rows: ManualInputRow[]) {
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

export function importRowValidationState(row: ManualInputRow, isDraftDirty: boolean) {
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

export function formatDraftSavedAt(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function currentDraftSavedAt() {
  return formatDraftSavedAt(new Date().toISOString());
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

export function groupManualRowsByTradeDate(rows: ManualInputRow[]) {
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

export function nextManualRowTradeDate(
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
