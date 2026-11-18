import { useEffect, useRef, useState } from 'react'

import { Button } from './Button'

export interface ConfirmButtonProps {
  /** 第一次点击前的按钮文案（如「删除」）。 */
  label: string
  /** 进入确认态后的文案（如「确认删除？」）；缺省为「确认？」。 */
  confirmLabel?: string
  /** 二次确认后执行的动作（通常是删除请求）。 */
  onConfirm: () => void
  /** 传入则按钮变窄小号（列表行内用）；缺省小号。 */
  className?: string
  disabled?: boolean
}

/**
 * 两次点击式确认按钮（r129）：删除类操作的统一入口。
 *
 * 不用 `window.confirm`（阻塞且样式出戏），也不引入模态框（历史列表里的删除
 * 是高频小动作，模态框太重）：第一次点击进入「确认？」态，再点才真正执行；
 * 失焦或 4 秒无操作自动退回，误触成本足够低。
 */
export function ConfirmButton({
  label,
  confirmLabel = '确认？',
  onConfirm,
  className,
  disabled = false,
}: ConfirmButtonProps) {
  const [arming, setArming] = useState(false)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [])

  const reset = (): void => {
    setArming(false)
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const handleClick = (): void => {
    if (!arming) {
      setArming(true)
      timerRef.current = window.setTimeout(reset, 4000)
      return
    }
    reset()
    onConfirm()
  }

  return (
    <Button
      type="button"
      variant={arming ? 'primary' : 'ghost'}
      size="sm"
      className={className === undefined ? 'sc-confirm-btn' : `sc-confirm-btn ${className}`}
      disabled={disabled}
      aria-label={arming ? confirmLabel : label}
      onBlur={reset}
      onClick={handleClick}
    >
      {arming ? confirmLabel : label}
    </Button>
  )
}
