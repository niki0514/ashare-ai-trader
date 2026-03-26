import { useEffect, useRef } from "react";

import type { ManualImportRowInput } from "../api";
import {
  MANUAL_SIDE_OPTIONS,
  MANUAL_VALIDITY_OPTIONS,
  importRowValidationState,
  isManualRowTouched,
  type ManualInputRow,
} from "../importHelpers";

type ImportManualGridProps = {
  touchedRowCount: number;
  selectedTouchedRowCount: number;
  allTouchedRowsSelected: boolean;
  someTouchedRowsSelected: boolean;
  previewValidCount: number;
  previewWarningCount: number;
  previewErrorCount: number;
  draftSavedAt: string;
  restoringDraft: boolean;
  manualRows: ManualInputRow[];
  isDraftDirty: boolean;
  isWorking: boolean;
  isRowSelected: (id: string) => boolean;
  onAddRow: () => void;
  onToggleAllTouchedRows: (selected: boolean) => void;
  onToggleRowSelection: (id: string, selected: boolean) => void;
  onUpdateRow: <K extends Exclude<keyof ManualInputRow, "id">>(
    id: string,
    key: K,
    value: ManualInputRow[K],
  ) => void;
  onRemoveRow: (id: string) => void;
};

export function ImportManualGrid({
  touchedRowCount,
  selectedTouchedRowCount,
  allTouchedRowsSelected,
  someTouchedRowsSelected,
  previewValidCount,
  previewWarningCount,
  previewErrorCount,
  draftSavedAt,
  restoringDraft,
  manualRows,
  isDraftDirty,
  isWorking,
  isRowSelected,
  onAddRow,
  onToggleAllTouchedRows,
  onToggleRowSelection,
  onUpdateRow,
  onRemoveRow,
}: ImportManualGridProps) {
  const selectAllRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!selectAllRef.current) {
      return;
    }

    selectAllRef.current.indeterminate = someTouchedRowsSelected && !allTouchedRowsSelected;
  }, [allTouchedRowsSelected, someTouchedRowsSelected]);

  return (
    <div className="manual-grid-shell">
      <div className="manual-grid-head">
        <div className="import-draft-meta">
          <span className="input-card-tag">待处理 {touchedRowCount} 条</span>
          <span className="input-card-tag">已选 {selectedTouchedRowCount} 条</span>
          <span className="input-card-tag import-summary-tag import-summary-tag-valid">
            通过 {previewValidCount}
          </span>
          <span className="input-card-tag import-summary-tag import-summary-tag-warning">
            警告 {previewWarningCount}
          </span>
          <span className="input-card-tag import-summary-tag import-summary-tag-error">
            错误 {previewErrorCount}
          </span>
          {draftSavedAt ? <span className="input-card-tag">最近保存 {draftSavedAt}</span> : null}
          {restoringDraft ? <span className="input-card-tag">正在恢复草稿...</span> : null}
        </div>
        <button
          type="button"
          className="manual-row-icon-button manual-add-button"
          onClick={onAddRow}
          disabled={isWorking}
          aria-label="新增一行"
          title="新增一行"
        >
          +
        </button>
      </div>
      <div className="manual-grid-table" role="table" aria-label="导入编辑表格">
        <div className="manual-grid-header manual-grid-header-expanded" role="row">
          <label className="manual-grid-select-all">
            <input
              ref={selectAllRef}
              type="checkbox"
              className="manual-grid-checkbox"
              checked={allTouchedRowsSelected}
              disabled={isWorking || touchedRowCount === 0}
              onChange={(event) => onToggleAllTouchedRows(event.target.checked)}
            />
            <span className="sr-only">全选或取消全选已填写记录</span>
          </label>
          <span>行号</span>
          <span>股票代码</span>
          <span>名称</span>
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
            const rowTouched = isManualRowTouched(row);
            const nameDisplay =
              row.nameStatus === "resolving"
                ? "识别中..."
                : row.nameStatus === "unresolved"
                  ? "未识别"
                  : row.name || "待识别";
            const nameTitle =
              row.nameStatus === "resolving"
                ? "正在按股票代码获取名称"
                : row.nameStatus === "unresolved"
                  ? "暂未识别到名称，请确认股票代码是否正确"
                  : row.name || "输入 6 位股票代码后自动获取名称";

            return (
              <div
                key={row.id}
                className={`manual-grid-body-row manual-grid-body-row-${
                  row.validationStatus?.toLowerCase() ?? "pending"
                }`}
                role="row"
              >
                <div className="manual-grid-row-fields manual-grid-row-fields-expanded">
                  <div className="manual-row-select-cell">
                    <label className="manual-grid-select-all">
                      <input
                        type="checkbox"
                        className="manual-grid-checkbox"
                        checked={rowTouched && isRowSelected(row.id)}
                        disabled={isWorking || !rowTouched}
                        onChange={(event) => onToggleRowSelection(row.id, event.target.checked)}
                      />
                      <span className="sr-only">选择第 {index + 1} 行用于提交</span>
                    </label>
                  </div>
                  <span className="manual-row-number">{index + 1}</span>
                  <label className="manual-field">
                    <span className="sr-only">第 {index + 1} 行股票代码</span>
                    <input
                      value={row.symbol}
                      disabled={isWorking}
                      onChange={(event) =>
                        onUpdateRow(row.id, "symbol", event.target.value.toUpperCase())
                      }
                      placeholder="如 600519"
                    />
                  </label>
                  <div
                    className={`manual-name-cell${row.name ? "" : " manual-name-cell-empty"}`}
                    title={nameTitle}
                  >
                    {nameDisplay}
                  </div>
                  <label className="manual-field">
                    <span className="sr-only">第 {index + 1} 行方向</span>
                    <select
                      value={row.side}
                      disabled={isWorking}
                      onChange={(event) =>
                        onUpdateRow(
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
                      onChange={(event) => onUpdateRow(row.id, "tradeDate", event.target.value)}
                    />
                  </label>
                  <label className="manual-field">
                    <span className="sr-only">第 {index + 1} 行挂单方式</span>
                    <select
                      value={row.validity}
                      disabled={isWorking}
                      onChange={(event) =>
                        onUpdateRow(
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
                      onChange={(event) => onUpdateRow(row.id, "price", event.target.value)}
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
                      onChange={(event) => onUpdateRow(row.id, "lots", event.target.value)}
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
                      onClick={() => onRemoveRow(row.id)}
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
  );
}
