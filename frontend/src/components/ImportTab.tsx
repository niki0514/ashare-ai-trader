import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { api, type ImportMode } from "../api";
import {
  clearManualRowValidation,
  createManualInputRow,
  createManualRowsFromBatch,
  createManualRowsFromPreview,
  currentDraftSavedAt,
  formatDraftSavedAt,
  groupManualRowsByTradeDate,
  importValidationSummary,
  isManualRowComplete,
  isManualRowTouched,
  nextManualRowTradeDate,
  type ManualInputRow,
} from "../importHelpers";
import { ImportManualGrid } from "./ImportManualGrid";
import { ImportOrdersPanel, type ImportOrderFilter } from "./ImportOrdersPanel";
import { isImportBlockedMarketStatus, isNonTradingMarketStatus } from "../orderHelpers";
import type {
  ImportPreviewRow,
  LatestImportBatch,
  MarketStatus,
  PendingOrderRow,
} from "../types";

type ImportTabProps = {
  marketStatus: MarketStatus;
  pendingOrders: PendingOrderRow[];
  targetTradeDate: string;
  onImportCommitted: () => Promise<unknown> | unknown;
};

const WORKFLOW_FEEDBACK_DURATION_MS = 2000;
const NAME_RESOLVE_DEBOUNCE_MS = 350;
const MANUAL_SYMBOL_PATTERN = /^\d{6}$/;

type ManualRowTradeDateGroup = ReturnType<typeof groupManualRowsByTradeDate>[number];

type PreviewedManualBatch = {
  tradeDate: string;
  rowIds: string[];
  batchId: string;
  rows: ImportPreviewRow[];
};

function hasResolvedManualName(name: string, symbol: string) {
  const normalizedName = name.trim();
  const normalizedSymbol = symbol.trim().toUpperCase();

  return normalizedName !== "" && normalizedName !== normalizedSymbol;
}

function nextPreviewNameState(
  row: ManualInputRow,
  preview: ImportPreviewRow,
): Pick<ManualInputRow, "name" | "nameStatus"> {
  if (hasResolvedManualName(preview.name, preview.symbol)) {
    return {
      name: preview.name,
      nameStatus: "resolved" as const,
    };
  }

  if (hasResolvedManualName(row.name, preview.symbol)) {
    return {
      name: row.name,
      nameStatus: "resolved" as const,
    };
  }

  return {
    name: "",
    nameStatus:
      row.nameStatus === "unresolved"
        ? ("unresolved" as ManualInputRow["nameStatus"])
        : ("idle" as ManualInputRow["nameStatus"]),
  };
}

function mergeManualRowsWithPreviewBatches(
  rows: ManualInputRow[],
  batches: PreviewedManualBatch[],
  preserveUnmatchedRows: boolean = false,
) {
  const previewByRowId = new Map<string, ImportPreviewRow>();
  const matchedRowIds = new Set<string>();

  for (const batch of batches) {
    batch.rowIds.forEach((rowId, index) => {
      matchedRowIds.add(rowId);
      const preview = batch.rows[index];
      if (preview) {
        previewByRowId.set(rowId, preview);
      }
    });
  }

  return rows.map((row) => {
    if (preserveUnmatchedRows && !matchedRowIds.has(row.id)) {
      return row;
    }

    if (!isManualRowTouched(row)) {
      return clearManualRowValidation(row);
    }

    const preview = previewByRowId.get(row.id);
    if (!preview) {
      return clearManualRowValidation(row);
    }

    const nextNameState = nextPreviewNameState(row, preview);

    return {
      ...row,
      tradeDate: preview.tradeDate,
      symbol: preview.symbol,
      name: nextNameState.name,
      nameStatus: nextNameState.nameStatus,
      side: preview.side,
      validity: preview.validity,
      price: String(preview.price),
      lots: String(preview.lots),
      validationStatus: preview.validationStatus,
      validationMessage: preview.validationMessage,
    };
  });
}

export function ImportTab({
  marketStatus,
  pendingOrders,
  targetTradeDate,
  onImportCommitted,
}: ImportTabProps) {
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
    isNonTradingMarketStatus(marketStatus) ? "all" : "active",
  );
  const [draftSavedAt, setDraftSavedAt] = useState<string>("");
  const [workflowFeedback, setWorkflowFeedback] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);
  const [isDraftDirty, setIsDraftDirty] = useState(false);
  const [draftFileName, setDraftFileName] = useState<string>("");
  const [validationBatchIds, setValidationBatchIds] = useState<Record<string, string>>({});
  const [selectedManualRowIds, setSelectedManualRowIds] = useState<Record<string, boolean>>({});
  const previousMarketStatusRef = useRef<MarketStatus | null>(null);
  const symbolNameCacheRef = useRef<Record<string, string | null>>({});
  const resolvingSymbolsRef = useRef<Record<string, boolean>>({});
  const [manualRows, setManualRows] = useState<ManualInputRow[]>([
    createManualInputRow({ tradeDate: targetTradeDate }),
  ]);
  const isImportWindowOpen = !isImportBlockedMarketStatus(marketStatus);

  const touchedManualRows = useMemo(() => manualRows.filter(isManualRowTouched), [manualRows]);
  const hasResolvingManualRows = manualRows.some((row) => row.nameStatus === "resolving");
  const hasIncompleteManualRows = touchedManualRows.some((row) => !isManualRowComplete(row));
  const manualRowsByTradeDate = useMemo(
    () => groupManualRowsByTradeDate(touchedManualRows),
    [touchedManualRows],
  );
  const manualTradeDates = useMemo(
    () => manualRowsByTradeDate.map((group) => group.tradeDate).filter((value) => value !== ""),
    [manualRowsByTradeDate],
  );
  const selectedTouchedManualRows = useMemo(
    () => touchedManualRows.filter((row) => selectedManualRowIds[row.id] !== false),
    [selectedManualRowIds, touchedManualRows],
  );
  const selectedTouchedRowCount = selectedTouchedManualRows.length;
  const hasIncompleteSelectedRows = selectedTouchedManualRows.some(
    (row) => !isManualRowComplete(row),
  );
  const selectedManualRowsByTradeDate = useMemo(
    () => groupManualRowsByTradeDate(selectedTouchedManualRows),
    [selectedTouchedManualRows],
  );
  const selectedTradeDates = useMemo(
    () =>
      selectedManualRowsByTradeDate
        .map((group) => group.tradeDate)
        .filter((value) => value !== ""),
    [selectedManualRowsByTradeDate],
  );
  const allTouchedRowsSelected =
    touchedManualRows.length > 0 &&
    touchedManualRows.every((row) => selectedManualRowIds[row.id] !== false);
  const someTouchedRowsSelected = touchedManualRows.some(
    (row) => selectedManualRowIds[row.id] !== false,
  );
  const validationSummary = useMemo(
    () => importValidationSummary(touchedManualRows),
    [touchedManualRows],
  );
  const previewValidCount = validationSummary.VALID;
  const previewWarningCount = validationSummary.WARNING;
  const previewErrorCount = validationSummary.ERROR;
  const canSaveManualDraft =
    manualTradeDates.length > 0 && !hasIncompleteManualRows && !hasResolvingManualRows;
  const canValidateAll = canSaveManualDraft;
  const hasSelectedTradeDatesBeforeSuggestedDate = selectedTradeDates.some(
    (tradeDate) => tradeDate < targetTradeDate,
  );
  const canSubmitImport =
    selectedTouchedRowCount > 0 &&
    !hasResolvingManualRows &&
    !hasIncompleteSelectedRows &&
    !hasSelectedTradeDatesBeforeSuggestedDate;
  const isWorking =
    uploading ||
    downloadingTemplate ||
    clearingDraft ||
    savingDraft ||
    validatingAll ||
    submittingImport ||
    deletingOrderId !== null ||
    restoringDraft;
  const importSubmitHint = !isImportWindowOpen
    ? "交易时段内可继续录入和校验，提交请在盘前、午休、收盘后或休市时进行。"
    : selectedTouchedRowCount === 0
      ? "请先勾选至少一条已填写记录。"
      : hasResolvingManualRows
        ? "股票名称识别中，请稍候后再提交。"
      : hasIncompleteSelectedRows
        ? "选中记录中仍有未补全行，可先取消勾选或补全后再提交。"
        : hasSelectedTradeDatesBeforeSuggestedDate
      ? `挂单时间不能早于 ${targetTradeDate}，已结束的交易日需调整到后续交易日后再提交。`
      : null;

  async function resolveSymbolNamesForTradeDate(tradeDate: string, symbols: string[]) {
    const nextSymbols = Array.from(
      new Set(
        symbols
          .map((symbol) => symbol.trim().toUpperCase())
          .filter(
            (symbol) =>
              MANUAL_SYMBOL_PATTERN.test(symbol) &&
              !resolvingSymbolsRef.current[symbol] &&
              symbolNameCacheRef.current[symbol] === undefined,
          ),
      ),
    );

    if (nextSymbols.length === 0) {
      return;
    }

    const nextSymbolsSet = new Set(nextSymbols);
    nextSymbols.forEach((symbol) => {
      resolvingSymbolsRef.current[symbol] = true;
    });

    setManualRows((currentRows) => {
      let changed = false;
      const nextRows = currentRows.map((row) => {
        const symbol = row.symbol.trim().toUpperCase();

        if (!nextSymbolsSet.has(symbol) || row.nameStatus === "resolving") {
          return row;
        }

        changed = true;
        return {
          ...row,
          name: "",
          nameStatus: "resolving" as const,
        };
      });

      return changed ? nextRows : currentRows;
    });

    try {
      const response = await api.resolveSymbols({
        targetTradeDate: tradeDate,
        symbols: nextSymbols,
      });
      const resolvedNames = new Map(
        response.rows.map((row) => [row.symbol, row.resolved && row.name.trim() !== "" ? row.name : null]),
      );

      nextSymbols.forEach((symbol) => {
        symbolNameCacheRef.current[symbol] = resolvedNames.get(symbol) ?? null;
        delete resolvingSymbolsRef.current[symbol];
      });

      setManualRows((currentRows) => {
        let changed = false;
        const nextRows = currentRows.map((row) => {
          const symbol = row.symbol.trim().toUpperCase();
          if (!nextSymbolsSet.has(symbol)) {
            return row;
          }

          const resolvedName = symbolNameCacheRef.current[symbol];
          const nextName = resolvedName ?? "";
          const nextNameStatus: ManualInputRow["nameStatus"] = resolvedName
            ? "resolved"
            : "unresolved";

          if (row.name === nextName && row.nameStatus === nextNameStatus) {
            return row;
          }

          changed = true;
          return {
            ...row,
            name: nextName,
            nameStatus: nextNameStatus,
          };
        });

        return changed ? nextRows : currentRows;
      });
    } catch {
      nextSymbols.forEach((symbol) => {
        symbolNameCacheRef.current[symbol] = null;
        delete resolvingSymbolsRef.current[symbol];
      });

      setManualRows((currentRows) => {
        let changed = false;
        const nextRows = currentRows.map((row) => {
          const symbol = row.symbol.trim().toUpperCase();

          if (!nextSymbolsSet.has(symbol) || row.nameStatus !== "resolving") {
            return row;
          }

          changed = true;
          return {
            ...row,
            name: "",
            nameStatus: "unresolved" as const,
          };
        });

        return changed ? nextRows : currentRows;
      });
    }
  }

  useEffect(() => {
    setManualRows((currentRows) =>
      currentRows.map((row) =>
        isManualRowTouched(row) ? row : { ...row, tradeDate: targetTradeDate },
      ),
    );
  }, [targetTradeDate]);

  useEffect(() => {
    setSelectedManualRowIds((currentSelections) => {
      const nextSelections: Record<string, boolean> = {};
      let changed = false;

      for (const row of manualRows) {
        if (!isManualRowTouched(row)) {
          if (row.id in currentSelections) {
            changed = true;
          }
          continue;
        }

        const nextSelected = currentSelections[row.id] ?? true;
        nextSelections[row.id] = nextSelected;

        if (!(row.id in currentSelections) || currentSelections[row.id] !== nextSelected) {
          changed = true;
        }
      }

      if (!changed && Object.keys(currentSelections).length !== Object.keys(nextSelections).length) {
        changed = true;
      }

      return changed ? nextSelections : currentSelections;
    });
  }, [manualRows]);

  useEffect(() => {
    if (
      !isNonTradingMarketStatus(previousMarketStatusRef.current) &&
      isNonTradingMarketStatus(marketStatus) &&
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
    for (const row of manualRows) {
      const symbol = row.symbol.trim().toUpperCase();
      if (!MANUAL_SYMBOL_PATTERN.test(symbol)) {
        continue;
      }
      if (hasResolvedManualName(row.name, symbol)) {
        symbolNameCacheRef.current[symbol] = row.name;
      }
    }
  }, [manualRows]);

  useEffect(() => {
    const pendingSymbolsByTradeDate = new Map<string, Set<string>>();

    setManualRows((currentRows) => {
      let changed = false;
      const nextRows = currentRows.map((row) => {
        const symbol = row.symbol.trim().toUpperCase();

        if (!MANUAL_SYMBOL_PATTERN.test(symbol) || row.nameStatus === "resolving") {
          return row;
        }

        if (hasResolvedManualName(row.name, symbol)) {
          return row;
        }

        const cachedName = symbolNameCacheRef.current[symbol];
        if (cachedName !== undefined) {
          const nextName = cachedName ?? "";
          const nextNameStatus: ManualInputRow["nameStatus"] = cachedName
            ? "resolved"
            : "unresolved";

          if (row.name === nextName && row.nameStatus === nextNameStatus) {
            return row;
          }

          changed = true;
          return {
            ...row,
            name: nextName,
            nameStatus: nextNameStatus,
          };
        }

        if (resolvingSymbolsRef.current[symbol]) {
          return row;
        }

        const tradeDate = row.tradeDate.trim() || targetTradeDate;
        const bucket = pendingSymbolsByTradeDate.get(tradeDate) ?? new Set<string>();
        bucket.add(symbol);
        pendingSymbolsByTradeDate.set(tradeDate, bucket);
        return row;
      });

      return changed ? nextRows : currentRows;
    });

    if (pendingSymbolsByTradeDate.size === 0) {
      return undefined;
    }

    const timerId = window.setTimeout(() => {
      pendingSymbolsByTradeDate.forEach((symbols, tradeDate) => {
        void resolveSymbolNamesForTradeDate(tradeDate, Array.from(symbols));
      });
    }, NAME_RESOLVE_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timerId);
    };
  }, [manualRows, targetTradeDate]);

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

  function setManualRowsFromPreviewBatches(
    batches: PreviewedManualBatch[],
    preserveUnmatchedRows: boolean = false,
  ) {
    setManualRows((currentRows) =>
      mergeManualRowsWithPreviewBatches(currentRows, batches, preserveUnmatchedRows),
    );
  }

  function markDraftDirty() {
    setIsDraftDirty(true);
    setWorkflowFeedback(null);
    resetValidationState();
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
    setManualRowsFromPreviewBatches(batches);
    setValidationBatchIds(
      Object.fromEntries(batches.map((batch) => [batch.tradeDate, batch.batchId])),
    );
    setDraftSavedAt(savedAt ?? currentDraftSavedAt());
    setDraftFileName(fileName ?? "");
    setIsDraftDirty(false);
    setWorkflowFeedback({ tone: "success", text: successText });
  }

  function handleToggleManualRowSelection(id: string, selected: boolean) {
    setSelectedManualRowIds((currentSelections) => ({
      ...currentSelections,
      [id]: selected,
    }));
  }

  function handleToggleAllTouchedRows(selected: boolean) {
    setSelectedManualRowIds((currentSelections) => {
      const nextSelections = { ...currentSelections };

      for (const row of touchedManualRows) {
        nextSelections[row.id] = selected;
      }

      return nextSelections;
    });
  }

  function updateManualRow<K extends Exclude<keyof ManualInputRow, "id">>(
    id: string,
    key: K,
    value: ManualInputRow[K],
  ) {
    markDraftDirty();
    setManualRows((currentRows) =>
      currentRows.map((row) =>
        row.id === id
          ? {
              ...row,
              [key]: value,
              ...(key === "symbol" ? { name: "", nameStatus: "idle" as const } : {}),
            }
          : row,
      ),
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
    setSelectedManualRowIds({});
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    setManualRows([createManualInputRow({ tradeDate: targetTradeDate })]);
  }

  async function previewManualBatches(
    groups: ManualRowTradeDateGroup[],
    mode: ImportMode = "DRAFT",
  ): Promise<PreviewedManualBatch[]> {
    return Promise.all(
      groups.map(async (group) => {
        const response = await api.previewImports({
          targetTradeDate: group.tradeDate,
          mode,
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
  }

  function applyLocalCommitFallback(
    currentRows: ManualInputRow[],
    committedBatches: PreviewedManualBatch[],
  ) {
    const committedRowIds = new Set(committedBatches.flatMap((batch) => batch.rowIds));
    const remainingRows = currentRows.filter((row) => !committedRowIds.has(row.id));
    const remainingTouchedRows = remainingRows.filter(isManualRowTouched);

    if (remainingTouchedRows.length === 0) {
      resetManualRowsState();
      return { remainingTouchedCount: 0 };
    }

    setManualRows(remainingRows.map(clearManualRowValidation));
    setValidationBatchIds({});
    setDraftSavedAt("");
    setIsDraftDirty(true);

    return { remainingTouchedCount: remainingTouchedRows.length };
  }

  async function syncRowsAfterCommit(
    currentRows: ManualInputRow[],
    committedBatches: PreviewedManualBatch[],
  ) {
    const committedRowIds = new Set(committedBatches.flatMap((batch) => batch.rowIds));
    const remainingRows = currentRows.filter((row) => !committedRowIds.has(row.id));
    const remainingTouchedRows = remainingRows.filter(isManualRowTouched);
    const remainingGroups = groupManualRowsByTradeDate(remainingTouchedRows);
    const remainingTradeDates = new Set(remainingGroups.map((group) => group.tradeDate));
    const datesToClear = Array.from(
      new Set(
        committedBatches
          .map((batch) => batch.tradeDate)
          .filter((tradeDate) => !remainingTradeDates.has(tradeDate)),
      ),
    );

    if (datesToClear.length > 0) {
      await Promise.all(datesToClear.map((tradeDate) => api.clearImportDrafts(tradeDate)));
    }

    if (remainingTouchedRows.length === 0) {
      resetManualRowsState();
      return { remainingTouchedCount: 0 };
    }

    const remainingDraftBatches = await previewManualBatches(remainingGroups, "DRAFT");
    setManualRows(mergeManualRowsWithPreviewBatches(remainingRows, remainingDraftBatches));
    setValidationBatchIds(
      Object.fromEntries(remainingDraftBatches.map((batch) => [batch.tradeDate, batch.batchId])),
    );
    setDraftSavedAt(currentDraftSavedAt());
    setIsDraftDirty(false);

    return { remainingTouchedCount: remainingTouchedRows.length };
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
        text: `文件解析成功，共 ${response.rows.length} 条。`,
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
      const responses = await previewManualBatches(manualRowsByTradeDate);
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
      const responses = await previewManualBatches(manualRowsByTradeDate);
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
    const currentRowsSnapshot = manualRows;
    const committedBatches: PreviewedManualBatch[] = [];

    try {
      const selectedBatches = await previewManualBatches(selectedManualRowsByTradeDate, "APPEND");
      const hasSelectedErrors = selectedBatches.some((batch) =>
        batch.rows.some((row) => row.validationStatus === "ERROR"),
      );

      if (hasSelectedErrors) {
        setManualRowsFromPreviewBatches(selectedBatches, true);
        setWorkflowFeedback({
          tone: "error",
          text: "选中记录存在校验错误，已刷新校验结果，请修正或取消勾选后重试。",
        });
        return;
      }

      for (const batch of selectedBatches) {
        const response = await api.commitImports({
          batchId: batch.batchId,
          mode: "APPEND",
        });
        importedCount += response.importedCount;
        committedBatches.push(batch);
      }

      const { remainingTouchedCount } = await syncRowsAfterCommit(
        currentRowsSnapshot,
        committedBatches,
      );
      setWorkflowFeedback({
        tone: "success",
        text:
          remainingTouchedCount > 0
            ? `已提交 ${importedCount} 条，未选记录已保留为草稿。`
            : `已提交 ${importedCount} 条，已生成委托记录，可在下方查看状态。`,
      });
      try {
        await onImportCommitted();
      } catch {
        // Keep the import workflow successful even if the follow-up refresh fails.
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "提交导入失败";
      let feedbackText = message;

      if (committedBatches.length > 0) {
        try {
          await syncRowsAfterCommit(currentRowsSnapshot, committedBatches);
        } catch (syncError) {
          const fallbackMessage =
            syncError instanceof Error ? syncError.message : "剩余草稿同步失败";
          applyLocalCommitFallback(currentRowsSnapshot, committedBatches);
          feedbackText = `已提交 ${importedCount} 条，剩余提交失败：${message}；${fallbackMessage}`;
        }
        if (feedbackText === message) {
          feedbackText = `已提交 ${importedCount} 条，剩余提交失败：${message}`;
        }
        try {
          await onImportCommitted();
        } catch {
          // Keep the partial-submit feedback focused on the import result itself.
        }
      } else if (message.includes("请重新校验")) {
        resetValidationState();
      }

      setWorkflowFeedback({
        tone: "error",
        text: feedbackText,
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
        <ImportManualGrid
          touchedRowCount={touchedManualRows.length}
          selectedTouchedRowCount={selectedTouchedRowCount}
          allTouchedRowsSelected={allTouchedRowsSelected}
          someTouchedRowsSelected={someTouchedRowsSelected}
          previewValidCount={previewValidCount}
          previewWarningCount={previewWarningCount}
          previewErrorCount={previewErrorCount}
          draftSavedAt={draftSavedAt}
          restoringDraft={restoringDraft}
          manualRows={manualRows}
          isDraftDirty={isDraftDirty}
          isWorking={isWorking}
          isRowSelected={(rowId) => selectedManualRowIds[rowId] !== false}
          onAddRow={() => addManualRow()}
          onToggleAllTouchedRows={handleToggleAllTouchedRows}
          onToggleRowSelection={handleToggleManualRowSelection}
          onUpdateRow={updateManualRow}
          onRemoveRow={removeManualRow}
        />
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
              {submittingImport ? "提交中..." : "提交已选"}
            </button>
          </div>
          {importSubmitHint ? <div className="import-submit-hint">{importSubmitHint}</div> : null}
        </div>
      </article>
      <ImportOrdersPanel
        pendingOrders={pendingOrders}
        orderFilter={orderFilter}
        deletingOrderId={deletingOrderId}
        onOrderFilterChange={setOrderFilter}
        onDeleteOrder={handleDeleteOrder}
      />
    </section>
  );
}
