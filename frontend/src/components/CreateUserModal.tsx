import type { FormEvent } from "react";

type CreateUserModalProps = {
  name: string;
  cash: string;
  errorMessage: string;
  loading: boolean;
  inputRef: { current: HTMLInputElement | null };
  onNameChange: (value: string) => void;
  onCashChange: (value: string) => void;
  onCancel: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
};

export function CreateUserModal({
  name,
  cash,
  errorMessage,
  loading,
  inputRef,
  onNameChange,
  onCashChange,
  onCancel,
  onSubmit,
}: CreateUserModalProps) {
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
