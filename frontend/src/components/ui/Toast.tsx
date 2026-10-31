import { useEffect, useRef, useState } from 'react'

/** 淡出时长：与 tokens.css `--fast`（120ms）同值，退场动画由 `.sc-toast.is-closing` 负责，这里只管时序。 */
const EXIT_MS = 120

export interface ToastProps {
  message: string
  /** 自增序号：2s 停留期内再次复制成功时重启计时（同一文案也不会提前消失，TECHNICAL §6 E-5）。 */
  seq?: number
  /** 停留时长（DESIGN §0.6：2s）。 */
  durationMs?: number
  onClose: () => void
}

/**
 * 轻量成功反馈：团队唯一的 Toast 出口（DESIGN §0.5 / §0.6 / §4）。
 * 自持「停留 durationMs → 淡出 EXIT_MS → onClose」计时；退场期间元素仍在树上，故 closing 态必须由组件持有。
 * 刻意不提供 error tone —— 失败一律走页内 InlineError，从组件形状上堵死误用。
 */
export function Toast({ message, seq = 0, durationMs = 2000, onClose }: ToastProps): JSX.Element {
  const [closing, setClosing] = useState(false)
  const onCloseRef = useRef(onClose)

  // 回调走 ref：父级内联箭头函数不会导致下方计时 effect 反复重启。
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    setClosing(false)
    const holdTimer = setTimeout(() => setClosing(true), durationMs)
    const exitTimer = setTimeout(() => onCloseRef.current(), durationMs + EXIT_MS)
    return () => {
      clearTimeout(holdTimer)
      clearTimeout(exitTimer)
    }
  }, [message, seq, durationMs])

  return (
    <div className={closing ? 'sc-toast is-closing' : 'sc-toast'} role="status" aria-live="polite">
      {message}
    </div>
  )
}
