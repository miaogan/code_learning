import { useId, useRef } from 'react'
import { Button } from './Button'
import { useModalFocus } from '../../lib/useModalFocus'

export interface NoticeModalProps {
  open: boolean
  title: string
  message: string
  /** 主行动作（例如「去设置」「去上传简历」），渲染为 primary 并默认拿到焦点。 */
  primaryLabel: string
  onPrimary: () => void
  /** 次要动作默认「知道了」；Esc / 遮罩点击同样走这里。 */
  closeLabel?: string
  onClose: () => void
}

/**
 * 告知型 Modal（r24）：单条说明 + 一个主行动作 + 一个收敛动作。
 * 与 ConfirmModal 的区别是**主动作才是 primary**（「去设置」「去上传简历」是正向引导，
 * 不是「做错会丢东西」的确认）；Esc / 遮罩 / 点「知道了」都只是关闭，不执行主动作。
 *
 * 焦点锁 / Esc / 焦点归还走 `lib/useModalFocus.ts`（与 ConfirmModal 共用，避免两处逻辑漂移）。
 */
export function NoticeModal({
  open,
  title,
  message,
  primaryLabel,
  onPrimary,
  closeLabel = '知道了',
  onClose,
}: NoticeModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const messageId = useId()

  useModalFocus(open, dialogRef, onClose)

  if (!open) return null

  return (
    <div
      className="sc-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
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
          <Button variant="primary" onClick={onPrimary}>
            {primaryLabel}
          </Button>
          <Button variant="ghost" onClick={onClose}>
            {closeLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
