import { useId, useRef } from 'react'
import { Button } from './Button'
import { useModalFocus } from '../../lib/useModalFocus'

export interface ConfirmModalProps {
  open: boolean
  title: string
  message: string
  /** 主动作（例如「仍然离开」）；按 DESIGN r3 §0.3 渲染为 ghost，安全动作才是 primary。 */
  confirmLabel: string
  /** 安全动作（例如「留在本页」）；渲染为 primary，并默认拿到焦点。 */
  cancelLabel: string
  onConfirm: () => void
  onCancel: () => void
}

/**
 * 确认 Modal（r3 新增，DESIGN r3 §0.3 / §4-3）：生成中离开保护等「做错会丢东西」的动作。
 *
 * 四条硬点：
 * 1. Esc = 取消；遮罩点击 = 取消（点内容不取消）。
 * 2. 焦点锁在 Modal 内（Tab/Shift+Tab 首尾循环），打开即入安全按钮，关闭后回到触发元素。
 * 3. 安全动作（`cancelLabel`）是 primary 且首焦点 —— 误触的代价必须是最小的。
 * 4. 遮罩色用 token 表达（`.sc-modal-backdrop` 内 color-mix，见 base.css），不加新颜色。
 *
 * 焦点锁 / Esc / 焦点归还走 `lib/useModalFocus.ts`（与 NoticeModal 共用，避免两处逻辑漂移）。
 */
export function ConfirmModal({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const messageId = useId()

  useModalFocus(open, dialogRef, onCancel)

  if (!open) return null

  return (
    <div
      className="sc-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div
        ref={dialogRef}
        className="sc-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={messageId}
      >
        <h2 className="sc-modal-title" id={titleId}>
          {title}
        </h2>
        <p className="sc-modal-message" id={messageId}>
          {message}
        </p>
        <div className="sc-modal-actions">
          <Button variant="primary" onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button variant="ghost" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
