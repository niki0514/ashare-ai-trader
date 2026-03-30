import type { ImportPreviewConfirmationItem } from "../types";

type ImportWarningConfirmModalProps = {
  batches: Array<{
    tradeDate: string;
    items: ImportPreviewConfirmationItem[];
  }>;
  loading: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void> | void;
};

export function ImportWarningConfirmModal({
  batches,
  loading,
  onCancel,
  onConfirm,
}: ImportWarningConfirmModalProps) {
  return (
    <div className="modal-backdrop" onClick={loading ? undefined : onCancel}>
      <div
        className="modal-card warning-confirmation-modal"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <h3>确认警告</h3>
            <p>以下记录没有确定性金融冲突，但仍需要你确认后才会提交。</p>
          </div>
          <button
            type="button"
            className="modal-close-button"
            onClick={onCancel}
            disabled={loading}
            aria-label="关闭警告确认弹窗"
          >
            关闭
          </button>
        </div>
        <div className="warning-confirmation-body">
          {batches.map((batch) => (
            <section key={batch.tradeDate} className="warning-confirmation-group">
              <h4>{batch.tradeDate}</h4>
              <div className="warning-confirmation-list">
                {batch.items.map((item) => (
                  <article
                    key={`${batch.tradeDate}-${item.code}-${item.rowNumbers.join("-")}`}
                    className="warning-confirmation-item"
                  >
                    <strong>{item.summary}</strong>
                    <span>
                      {item.rowNumbers.length > 0
                        ? `涉及行号：${item.rowNumbers.join(", ")}`
                        : "这是批次级确认项。"}
                    </span>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
        <div className="modal-actions">
          <button
            type="button"
            className="user-secondary-button"
            onClick={onCancel}
            disabled={loading}
          >
            返回调整
          </button>
          <button
            type="button"
            className="user-primary-button"
            onClick={() => void onConfirm()}
            disabled={loading}
          >
            {loading ? "提交中..." : "确认提交"}
          </button>
        </div>
      </div>
    </div>
  );
}
