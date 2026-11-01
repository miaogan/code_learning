import { useEffect, useMemo, useRef } from 'react'
import type { InterviewSessionQuestion } from '../../api/types'
import { ChatBubble } from './ChatBubble'
import { bubblesOf, questionNoOf } from './chatModel'

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export interface ChatStreamProps {
  questions: InterviewSessionQuestion[]
  /** 本轮评分中：在面试官侧追加占位泡（不打全屏 loader，已答内容始终可见） */
  pending: boolean
  /** 流顶一行提示（可选，如「已恢复本场会话」）；不进入气泡序列 */
  notice?: string
  /** 滚动锚点变化的回调（页面可据此同步 ?q= 深链；不改变气泡渲染） */
  onQuestionFocus?: (id: string) => void
}

/**
 * 气泡流容器：只做序列推导与滚动锚点，条目外观全在 ChatBubble 内。
 * 恢复会话（AC-9）时历史气泡不参与入场动画：只有「本次新出现」的气泡带 `.is-new`。
 */
export function ChatStream({ questions, pending, notice, onQuestionFocus }: ChatStreamProps) {
  const bubbles = useMemo(() => bubblesOf(questions), [questions])

  const nodesRef = useRef(new Map<string, HTMLDivElement>())
  const pendingRef = useRef<HTMLDivElement | null>(null)
  const seenRef = useRef<Set<string>>(new Set())
  const notifyRef = useRef<string | null>(null)

  // 上一次已提交渲染出现过的 id（只在 effect 里更新，StrictMode 双渲染不会误判）。
  useEffect(() => {
    seenRef.current = new Set(bubbles.map((bubble) => bubble.id))
  }, [bubbles])

  // 首批内容（首场第 1 泡 / 恢复会话的全部气泡）不播入场动画（DESIGN §0.4 禁止重播）；
  // seenRef 非空后新追加的条目才带 `.is-new`。
  const newIds = useMemo(() => {
    if (seenRef.current.size === 0) return []
    return bubbles.filter((bubble) => !seenRef.current.has(bubble.id)).map((bubble) => bubble.id)
  }, [bubbles])

  // 锚点 = 最后一条候选人气泡（没有作答则最后一条面试官泡）：滚到它的评分区完整可见。
  const anchorId = useMemo(() => {
    for (let i = bubbles.length - 1; i >= 0; i -= 1) {
      if (bubbles[i].role === 'candidate') return bubbles[i].id
    }
    return bubbles.length > 0 ? bubbles[bubbles.length - 1].id : null
  }, [bubbles])

  useEffect(() => {
    const node = pending ? pendingRef.current : anchorId ? nodesRef.current.get(anchorId) ?? null : null
    if (!node) return
    node.scrollIntoView({ block: 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  }, [anchorId, pending])

  const anchorQuestionId = useMemo(() => {
    const anchor = bubbles.find((bubble) => bubble.id === anchorId)
    return anchor?.question?.id ?? null
  }, [anchorId, bubbles])

  useEffect(() => {
    if (!anchorQuestionId || anchorQuestionId === notifyRef.current) return
    notifyRef.current = anchorQuestionId
    onQuestionFocus?.(anchorQuestionId)
  }, [anchorQuestionId, onQuestionFocus])

  return (
    <div className="sc-iq-stream">
      {notice ? (
        <p className="sc-iq-notice" role="status">
          {notice}
        </p>
      ) : null}

      {bubbles.map((bubble) => {
        const classes = ['sc-iq-slot']
        if (newIds.includes(bubble.id)) classes.push('is-new')
        const parentNo = bubble.question?.parent_id ? questionNoOf(bubble.question.parent_id) : undefined
        return (
          <div
            key={bubble.id}
            className={classes.join(' ')}
            ref={(node) => {
              if (node) nodesRef.current.set(bubble.id, node)
              else nodesRef.current.delete(bubble.id)
            }}
          >
            <ChatBubble bubble={bubble} parentNo={parentNo} />
          </div>
        )
      })}

      {pending ? (
        <div className="sc-iq-slot is-new" ref={pendingRef}>
          <article className="sc-iq-msg sc-iq-msg--interviewer" aria-labelledby="iq-pending-who">
            <div className="sc-iq-who-row" id="iq-pending-who">
              <span className="sc-iq-dot" aria-hidden="true" />
              <span className="sc-iq-who">面试官</span>
            </div>
            <div className="sc-iq-bubble sc-iq-bubble--interviewer sc-iq-bubble--pending" role="status">
              <span className="sc-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
              <span className="sc-iq-pending-text">正在评分并准备下一问…</span>
            </div>
          </article>
        </div>
      ) : null}
    </div>
  )
}
