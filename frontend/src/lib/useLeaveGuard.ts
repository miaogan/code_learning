/**
 * 离开保护 hook（r147 A3：此前四页逐字重复同一套 effect）。
 *
 * 口径（与原四页实现一致，行为零变化）：
 * - `active` 为真时：`beforeunload` 拦浏览器刷新/关闭；document 捕获阶段拦**跨页 `<a href>`**
 *   （锚点、外链、当前页链接放行），拦下后把 href 存进 `pendingLeave` 交给页面弹确认框；
 * - `active` 为假时清空 `pendingLeave`（恢复原状态，不残留「离开」弹框）；
 * - `confirmLeave(onLeave?)`：确认后先跑页面自己的收尾（如中止在途上传），再跳转；
 * - ConfirmModal **留在各页渲染**——标题/正文/按钮文案是产品口径，四页各不相同。
 *
 * 页面用法：
 * ```tsx
 * const { pendingLeave, confirmLeave, cancelLeave } = useLeaveGuard(stage === 'running' && hasAnyAnswer)
 * <ConfirmModal open={pendingLeave !== null} onConfirm={() => confirmLeave()} onCancel={cancelLeave} ... />
 * ```
 */

import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

export function useLeaveGuard(active: boolean, onLeave?: () => void): {
  pendingLeave: string | null
  confirmLeave: () => void
  cancelLeave: () => void
} {
  const [pendingLeave, setPendingLeave] = useState<string | null>(null)
  const navigate = useNavigate()
  const pathname = useLocation().pathname

  useEffect(() => {
    if (!active) {
      setPendingLeave(null)
      return
    }
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    const onClickCapture = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest('a[href]') : null
      if (!target) return
      const href = target.getAttribute('href')
      if (!href || href.startsWith('#') || /^[a-z]+:/i.test(href) || href === pathname) return
      event.preventDefault()
      event.stopPropagation()
      setPendingLeave(href)
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('click', onClickCapture, true)
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('click', onClickCapture, true)
    }
  }, [active, pathname])

  const confirmLeave = (): void => {
    const href = pendingLeave
    setPendingLeave(null)
    onLeave?.()
    if (href !== null) navigate(href)
  }

  const cancelLeave = (): void => {
    setPendingLeave(null)
  }

  return { pendingLeave, confirmLeave, cancelLeave }
}
