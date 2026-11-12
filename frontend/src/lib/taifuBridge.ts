/**
 * r82 太傅唤起桥：页面组件 → 全局浮窗的唯一通道。
 *
 * 为什么用 `CustomEvent` 而不是 Context：浮窗挂在 `App` 的兄弟位置（路由树之外），
 * 页面组件在路由树里；为了一个「从这一行叫太傅」的交互去改组件树结构不划算。
 * 事件是同步的 —— 点完立刻开面板、填问题，没有状态延迟。
 *
 * 校验放在这里而不是只靠服务端：焦点不合法时服务端会**静默忽略**（当没传），
 * 用户会以为「它读了我这一条」；前端先挡住，才谈得上诚实。
 */

import type { TaifuFocus } from '../api/types'

export const TAIFU_ASK_EVENT = 'sc:taifu-ask'

export interface TaifuAsk {
  question: string
  focus: TaifuFocus
  /** 面板顶部的「正在问：…」文案，由页面提供 —— 它最清楚这一条叫什么。 */
  label: string
}

/** 焦点闭集校验 + 归一：不合法返回 `null`（不猜、不兜底成第一条）。 */
export function normalizeFocus(focus: TaifuFocus): TaifuFocus | null {
  if (focus.kind === 'weakness') {
    return Number.isInteger(focus.index) && focus.index >= 1 ? focus : null
  }
  if (focus.kind === 'attempt') {
    const questionId = focus.question_id.trim()
    return questionId ? { kind: 'attempt', question_id: questionId } : null
  }
  if (focus.kind === 'resume') {
    const anchor = focus.anchor.replace(/\s+/g, ' ').trim()
    return anchor ? { kind: 'resume', anchor } : null
  }
  return null
}

/** 唤起太傅：焦点或问题任一不合适就不发事件，返回是否发出（页面可用它给失败提示）。 */
export function askTaifu(ask: TaifuAsk): boolean {
  const focus = normalizeFocus(ask.focus)
  const question = ask.question.replace(/\s+/g, ' ').trim()
  if (focus === null || !question) return false
  window.dispatchEvent(
    new CustomEvent<TaifuAsk>(TAIFU_ASK_EVENT, {
      detail: { question, focus, label: ask.label.replace(/\s+/g, ' ').trim() },
    }),
  )
  return true
}

/** 浮窗侧订阅；返回取消订阅函数（组件卸载必须调，避免重复挂监听）。 */
export function onTaifuAsk(handler: (ask: TaifuAsk) => void): () => void {
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<TaifuAsk | undefined>).detail
    // 事件可能来自别处（测试 / 第三方脚本），形状不对就忽略，不让浮窗崩在半路。
    if (!detail || !detail.focus) return
    handler(detail)
  }
  window.addEventListener(TAIFU_ASK_EVENT, listener)
  return () => window.removeEventListener(TAIFU_ASK_EVENT, listener)
}
