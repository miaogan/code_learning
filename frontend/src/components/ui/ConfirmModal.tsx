import { useCallback, useEffect, useId, useRef } from 'react'
import { Button } from './Button'

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

/** 可聚焦元素选择器：Modal 内 Tab 循环只在可见、可用的控件之间走。 */
const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * 确认 Modal（r3 新增，DESIGN r3 §0.3 / §4-3）：生成中离开保护等「做错会丢东西」的动作。
 *
 * 四条硬点：
 * 1. Esc = 取消；遮罩点击 = 取消（点内容不取消）。
 * 2. 焦点锁在 Modal 内（Tab/Shift+Tab 首尾循环），打开即入安全按钮，关闭后回到触发元素。
 * 3. 安全动作（`cancelLabel`）是 primary 且首焦点 —— 误触的代价必须是最小的。
 * 4. 遮罩色用 token 表达（`.sc-modal-backdrop` 内 color-mix，见 base.css），不加新颜色。
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
  // 回调走 ref：父级内联箭头函数不会让下面的焦点/键盘 effect 反复重启（同 Toast 的写法）。
  const onCancelRef = useRef(onCancel)
  const onConfirmRef = useRef(onConfirm)
  const restoreRef = useRef<HTMLElement | null>(null)
  const titleId = useId()
  const messageId = useId()

  useEffect(() => {
    onCancelRef.current = onCancel
    onConfirmRef.current = onConfirm
  }, [onCancel, onConfirm])

  const focusables = useCallback((): HTMLElement[] => {
    const root = dialogRef.current
    if (root === null) return []
    return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
  }, [])

  useEffect(() => {
    if (!open) return undefined
    restoreRef.current = document.activeElement as HTMLElement | null
    // 焦点入 Modal 首按钮（安全动作），见 DESIGN r3 §0.3 / §5「焦点」
    focusables()[0]?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCancelRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) {
        event.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || active === null || !dialogRef.current?.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      // 关闭后焦点回到触发按钮（DESIGN r3 §5「焦点」）
      const restore = restoreRef.current
      restoreRef.current = null
      if (restore !== null && typeof restore.focus === 'function') restore.focus()
    }
  }, [open, focusables])

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
