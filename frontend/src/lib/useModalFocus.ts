import { useCallback, useEffect, useRef } from 'react'
import type { RefObject } from 'react'

/** 可聚焦元素选择器：Modal 内 Tab 循环只在可见、可用的控件之间走。 */
const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Modal 焦点治理（DESIGN r3 §0.3 / §5「焦点」）：
 * 打开即入首控件、Tab / Shift+Tab 首尾循环、Esc 交由调用方、关闭后焦点归还触发元素。
 *
 * ConfirmModal 与 NoticeModal 共用这一份，避免两处键盘逻辑各改一半而漂移。
 * 首焦点由**渲染顺序**决定：确认框把安全动作（primary）放在前面，告知框把主动作放在前面。
 *
 * @param open 受控打开态
 * @param dialogRef 弹框内容容器
 * @param onEscape Esc 的行为：确认框 = 取消，告知框 = 关闭
 */
export function useModalFocus(
  open: boolean,
  dialogRef: RefObject<HTMLDivElement>,
  onEscape: () => void,
): void {
  // 回调走 ref：父级内联箭头函数不会让下面的焦点/键盘 effect 反复重启（同 Toast 的写法）。
  const escapeRef = useRef(onEscape)
  const restoreRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    escapeRef.current = onEscape
  }, [onEscape])

  const focusables = useCallback((): HTMLElement[] => {
    const root = dialogRef.current
    if (root === null) return []
    return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
  }, [dialogRef])

  useEffect(() => {
    if (!open) return undefined
    restoreRef.current = document.activeElement as HTMLElement | null
    focusables()[0]?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        escapeRef.current()
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
      const restore = restoreRef.current
      restoreRef.current = null
      if (restore !== null && typeof restore.focus === 'function') restore.focus()
    }
  }, [open, focusables, dialogRef])
}
