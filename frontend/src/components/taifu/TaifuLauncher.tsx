import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import type {
  CSSProperties,
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from 'react'
import { Link, useLocation } from 'react-router-dom'

import { ApiError, api } from '../../api/client'
import type { TaifuMemoryItem, TaifuMessage } from '../../api/types'
import {
  TAIFU_QUESTION_MAX,
  TAIFU_SAMPLES,
  canSend,
  clampQuestion,
  paragraphsOf,
  uniqueCitations,
} from '../../lib/taifuChat'
import {
  clampTaifuPosition,
  defaultTaifuPosition,
  readStoredTaifuPosition,
  taifuPanelLayout,
  writeStoredTaifuPosition,
  type TaifuPosition,
} from '../../lib/taifuPosition'

const DRAG_THRESHOLD = 5
const NUDGE_STEP = 8
const NUDGE_STEP_FAST = 24

const PAGE_LABEL: Record<string, string> = {
  '/': '投卷',
  '/profile': '立传',
  '/interview': '召对',
  '/exam': '科考',
  '/report': '医案',
  '/history': '战绩',
  '/eval': '评鉴',
  '/polish': '修文',
  '/versions': '校勘',
  '/archive': '卷宗',
  '/practice': '演武',
  '/pioneer': '先锋',
  '/guozijian': '国子监',
  '/search': '检索',
  '/learn': '学堂',
  '/settings': '典制',
}

interface DragState {
  pointerId: number
  startX: number
  startY: number
  origin: TaifuPosition
}

type ThreadStatus = 'idle' | 'loading' | 'ready' | 'error'

function pageLabelOf(pathname: string): string {
  if (pathname.startsWith('/learn/')) return '学堂'
  return PAGE_LABEL[pathname] ?? '当前页面'
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : '请求失败，请稍后重试'
}

/** 记忆入口的按钮文案：没读过时不报数字（不猜条数），读过才给准确值。 */
function memoriesLabel(memories: TaifuMemoryItem[] | null): string {
  if (memories === null) return '记忆'
  if (memories.length === 0) return '记忆 · 空'
  return `记忆 · ${memories.length} 条`
}

export interface TaifuLauncherProps {
  /** 当前登录账号：位置记忆与对话都按账号隔离，换账号不会复用上一个人的记录。 */
  userId: string
}

/**
 * r77 太傅：右下角可拖拽的参谋入口 + 只读站内档案的对话面板。
 *
 * 交互约定：
 * - 收起状态**零请求**（打开面板才读对话历史），常驻件不能有后台开销；
 * - 桌面从印章旁展开、窄屏由 CSS 接管为底部面板；
 * - 方向键 8px / Shift 24px 微调，Home 归位，Esc 收起并归还焦点；
 * - 引用是服务端白名单校验过的站内路由，点开即跳转，路由变化自动收起面板。
 *
 * 层级：印章 / 浮窗 15 —— 高于 topbar(10)、低于 Toast(20) 与 Modal(40)。
 */
export function TaifuLauncher({ userId }: TaifuLauncherProps) {
  const location = useLocation()
  const [viewport, setViewport] = useState(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
  }))
  const [position, setPosition] = useState<TaifuPosition>(() => {
    const saved = readStoredTaifuPosition(userId, window.innerWidth, window.innerHeight)
    return saved ?? defaultTaifuPosition(window.innerWidth, window.innerHeight)
  })
  const positionRef = useRef(position)
  const [open, setOpen] = useState(false)
  const [dragging, setDragging] = useState(false)
  const dragRef = useRef<DragState | null>(null)
  const movedRef = useRef(false)
  const suppressClickRef = useRef(false)
  const fabRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const titleId = useId()
  const panelId = useId()

  const [thread, setThread] = useState<TaifuMessage[]>([])
  const [threadStatus, setThreadStatus] = useState<ThreadStatus>('idle')
  const [threadError, setThreadError] = useState('')
  const [question, setQuestion] = useState('')
  const [pending, setPending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [notice, setNotice] = useState('')
  const [meta, setMeta] = useState<{ materials: number; dropped: number; added: number } | null>(
    null,
  )
  const [clearArmed, setClearArmed] = useState(false)
  const [clearing, setClearing] = useState(false)
  // r81 长期记忆：默认收起，展开时才读（与线程同一口径：收起态零请求）。
  const [memories, setMemories] = useState<TaifuMemoryItem[] | null>(null)
  const [memoriesStatus, setMemoriesStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>(
    'idle',
  )
  const [memoriesError, setMemoriesError] = useState('')
  const [memoriesOpen, setMemoriesOpen] = useState(false)
  const [forgetArmed, setForgetArmed] = useState(false)
  const [forgetting, setForgetting] = useState(false)

  const moveTo = useCallback(
    (next: TaifuPosition, persist: boolean) => {
      const clamped = clampTaifuPosition(next, viewport.width, viewport.height)
      positionRef.current = clamped
      setPosition(clamped)
      if (persist) writeStoredTaifuPosition(userId, clamped)
    },
    [userId, viewport.height, viewport.width],
  )

  const resetPosition = useCallback(() => {
    const next = defaultTaifuPosition(viewport.width, viewport.height)
    positionRef.current = next
    setPosition(next)
    writeStoredTaifuPosition(userId, next)
  }, [userId, viewport.height, viewport.width])

  const loadThread = useCallback(async () => {
    setThreadStatus('loading')
    setThreadError('')
    try {
      const data = await api.taifuThread(20)
      setThread(data.messages)
      setThreadStatus('ready')
    } catch (error) {
      setThreadError(errorText(error))
      setThreadStatus('error')
    }
  }, [])

  useEffect(() => {
    const syncViewport = () => {
      const width = window.innerWidth
      const height = window.innerHeight
      setViewport({ width, height })
      const next = clampTaifuPosition(positionRef.current, width, height)
      positionRef.current = next
      setPosition(next)
    }
    window.addEventListener('resize', syncViewport)
    window.visualViewport?.addEventListener('resize', syncViewport)
    return () => {
      window.removeEventListener('resize', syncViewport)
      window.visualViewport?.removeEventListener('resize', syncViewport)
    }
  }, [])

  // 路由变化后旧页面的上下文已失效，收起浮窗，等用户重新发问。
  // `hash` 也要看：引用可能指向当前页的锚点（`/report#weakness-3`），只变 hash 时 pathname 不变。
  useEffect(() => {
    setOpen(false)
  }, [location.pathname, location.hash])

  // 打开面板才读历史：收起状态不发请求（常驻件零后台开销）。
  useEffect(() => {
    if (!open) {
      setClearArmed(false)
      setSendError('')
      return
    }
    if (threadStatus === 'idle') void loadThread()
  }, [open, threadStatus, loadThread])

  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      fabRef.current?.focus()
    }
    document.addEventListener('keydown', closeOnEscape)
    const focusTimer = window.setTimeout(() => closeRef.current?.focus(), 0)
    return () => {
      document.removeEventListener('keydown', closeOnEscape)
      window.clearTimeout(focusTimer)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const closeOnOutside = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (panelRef.current?.contains(target) || fabRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutside, true)
    return () => document.removeEventListener('pointerdown', closeOnOutside, true)
  }, [open])

  // 新消息 / 等待态 / 展开记忆都把视图带到最底部：用户不该手动滚才能看到刚来的内容。
  useEffect(() => {
    if (!open) return
    const body = bodyRef.current
    if (body === null) return
    body.scrollTop = body.scrollHeight
  }, [open, thread.length, pending, notice, sendError, memoriesOpen, memories?.length])

  const panelStyle = useMemo<CSSProperties | undefined>(() => {
    const layout = taifuPanelLayout(position, viewport.width, viewport.height)
    if (layout === null) return undefined
    return {
      left: `${layout.left}px`,
      top: `${layout.top}px`,
      width: `${layout.width}px`,
      height: `${layout.height}px`,
    }
  }, [position, viewport.height, viewport.width])

  const send = useCallback(async () => {
    const text = clampQuestion(question)
    if (!canSend(text, pending)) return
    const localId = `local-${Date.now()}`
    const localMessage: TaifuMessage = {
      id: localId,
      role: 'user',
      content: text,
      citations: [],
      created_at: new Date().toISOString(),
    }
    setQuestion('')
    setPending(true)
    setSendError('')
    setNotice('')
    setThread((current) => [...current, localMessage])
    try {
      const reply = await api.taifuChat(text, location.pathname)
      setMeta({
        materials: reply.materials_used,
        dropped: reply.dropped_citations,
        added: reply.memories_added,
      })
      setNotice(reply.notice)
      if (reply.memories_added > 0) {
        // 记忆变了：丢掉缓存让计数重新读（展开态会立刻重拉，收起态等下次展开）。
        // 不能让旧数组留在界面上充当「最新条数」。
        setMemories(null)
        setMemoriesStatus('idle')
      }
      if (!reply.reply) {
        // 服务端没有可回答的内容（如空档案）时它不会落库，这里也必须收回问句，
        // 否则界面上会留下一条刷新即消失的「有问无答」。
        setThread((current) => current.filter((item) => item.id !== localId))
        setQuestion(text)
        return
      }
      setThread((current) => [
        ...current,
        {
          id: `local-a-${Date.now()}`,
          role: 'assistant',
          content: reply.reply,
          citations: reply.citations,
          created_at: reply.created_at || new Date().toISOString(),
        },
      ])
    } catch (error) {
      // 失败不留半条对话：收回这句问话，让用户改一改或直接重发。
      setThread((current) => current.filter((item) => item.id !== localId))
      setQuestion(text)
      setSendError(errorText(error))
    } finally {
      setPending(false)
    }
  }, [location.pathname, pending, question])

  const loadMemories = useCallback(async () => {
    setMemoriesStatus('loading')
    setMemoriesError('')
    try {
      const data = await api.taifuMemories()
      setMemories(data.items)
      setMemoriesStatus('ready')
    } catch (error) {
      setMemoriesError(errorText(error))
      setMemoriesStatus('error')
    }
  }, [])

  const forgetOne = useCallback(async (id: string) => {
    setForgetting(true)
    setMemoriesError('')
    try {
      await api.taifuForgetMemory(id)
      setMemories((current) => (current === null ? current : current.filter((item) => item.id !== id)))
    } catch (error) {
      setMemoriesError(errorText(error))
    } finally {
      setForgetting(false)
    }
  }, [])

  const forgetAll = useCallback(async () => {
    if (!forgetArmed) {
      setForgetArmed(true)
      return
    }
    setForgetting(true)
    setMemoriesError('')
    try {
      await api.taifuForgetAllMemories()
      setMemories([])
    } catch (error) {
      setMemoriesError(errorText(error))
    } finally {
      setForgetting(false)
      setForgetArmed(false)
    }
  }, [forgetArmed])

  // 记忆展开时才读：收起态与「从没打开过记忆」都不发请求。
  useEffect(() => {
    if (!memoriesOpen) {
      setForgetArmed(false)
      return
    }
    if (memoriesStatus === 'idle') void loadMemories()
  }, [memoriesOpen, memoriesStatus, loadMemories])

  const clearThread = useCallback(async () => {
    if (!clearArmed) {
      setClearArmed(true)
      return
    }
    setClearing(true)
    setSendError('')
    try {
      await api.taifuClear()
      setThread([])
      setNotice('')
      setMeta(null)
      setThreadStatus('ready')
    } catch (error) {
      setSendError(errorText(error))
    } finally {
      setClearing(false)
      setClearArmed(false)
    }
  }, [clearArmed])

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void send()
  }

  const onPointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    const rect = event.currentTarget.getBoundingClientRect()
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      origin: { x: rect.left, y: rect.top },
    }
    movedRef.current = false
    suppressClickRef.current = false
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current
    if (drag === null || drag.pointerId !== event.pointerId) return
    if (!movedRef.current) {
      const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY)
      if (distance < DRAG_THRESHOLD) return
      movedRef.current = true
      setDragging(true)
      setOpen(false)
    }
    moveTo(
      {
        x: drag.origin.x + (event.clientX - drag.startX),
        y: drag.origin.y + (event.clientY - drag.startY),
      },
      false,
    )
  }

  const finishDrag = (event: ReactPointerEvent<HTMLButtonElement>, persist: boolean) => {
    const drag = dragRef.current
    if (drag === null || drag.pointerId !== event.pointerId) return
    if (movedRef.current) {
      suppressClickRef.current = true
      if (persist) writeStoredTaifuPosition(userId, positionRef.current)
    }
    dragRef.current = null
    setDragging(false)
  }

  const onClick = () => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      return
    }
    setOpen((current) => !current)
  }

  const onKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const step = event.shiftKey ? NUDGE_STEP_FAST : NUDGE_STEP
    if (event.key === 'Home') {
      event.preventDefault()
      resetPosition()
      return
    }
    const delta =
      event.key === 'ArrowLeft'
        ? { x: -step, y: 0 }
        : event.key === 'ArrowRight'
          ? { x: step, y: 0 }
          : event.key === 'ArrowUp'
            ? { x: 0, y: -step }
            : event.key === 'ArrowDown'
              ? { x: 0, y: step }
              : null
    if (delta === null) return
    event.preventDefault()
    moveTo(
      {
        x: positionRef.current.x + delta.x,
        y: positionRef.current.y + delta.y,
      },
      true,
    )
  }

  return (
    <>
      <button
        ref={fabRef}
        type="button"
        className={
          ['sc-taifu-fab', dragging ? 'is-dragging' : '', open ? 'is-open' : '']
            .filter(Boolean)
            .join(' ')
        }
        style={{ left: `${position.x}px`, top: `${position.y}px` }}
        aria-label="问太傅"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        title="拖动调整位置；方向键微调，Home 归位"
        onClick={onClick}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={(event) => finishDrag(event, true)}
        onPointerCancel={(event) => finishDrag(event, true)}
        onKeyDown={onKeyDown}
      >
        <span aria-hidden="true">傅</span>
      </button>

      {open ? (
        <div
          ref={panelRef}
          id={panelId}
          className="sc-taifu-panel"
          style={panelStyle}
          role="dialog"
          aria-labelledby={titleId}
        >
          <header className="sc-taifu-head">
            <div className="sc-taifu-brand">
              <span className="sc-taifu-seal" aria-hidden="true">傅</span>
              <div>
                <h2 className="sc-taifu-title" id={titleId}>太傅</h2>
                <p className="sc-taifu-sub">你的跃迁参谋 · 只读</p>
              </div>
            </div>
            <div className="sc-taifu-headactions">
              <button
                type="button"
                className="sc-taifu-textbtn"
                onClick={resetPosition}
                title="把印章放回右下角"
              >
                归位
              </button>
              <button
                ref={closeRef}
                type="button"
                className="sc-taifu-close"
                aria-label="关闭太傅"
                onClick={() => setOpen(false)}
              >
                ×
              </button>
            </div>
          </header>

          <div className="sc-taifu-context">
            <span className="sc-taifu-contextdot" aria-hidden="true" />
            当前：{pageLabelOf(location.pathname)}
          </div>

          <div className="sc-taifu-body" ref={bodyRef}>
            {threadStatus === 'loading' ? (
              <p className="sc-taifu-hint">正在读取你的站内记录…</p>
            ) : null}

            {threadStatus === 'error' ? (
              <div className="sc-taifu-error" role="alert">
                <p>{threadError}</p>
                <button type="button" className="sc-taifu-textbtn" onClick={() => void loadThread()}>
                  重试
                </button>
              </div>
            ) : null}

            {threadStatus === 'ready' && thread.length === 0 ? (
              <>
                <p className="sc-taifu-bubble">
                  我是太傅。我会先读你的画像、测评、练习与学习记录，再回答「先补什么、为什么、怎么补」。
                </p>
                <p className="sc-taifu-label">可以这样问</p>
                <ul className="sc-taifu-samples">
                  {TAIFU_SAMPLES.map((sample) => (
                    <li key={sample}>
                      <button
                        type="button"
                        className="sc-taifu-sample"
                        onClick={() => {
                          setQuestion(sample)
                          inputRef.current?.focus()
                        }}
                      >
                        {sample}
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}

            {thread.map((message) => (
              <div
                key={message.id}
                className={message.role === 'user' ? 'sc-taifu-msg is-user' : 'sc-taifu-msg'}
              >
                <div className="sc-taifu-msgtext">
                  {paragraphsOf(message.content).map((paragraph, index) => (
                    <p key={`${message.id}-${index}`}>{paragraph}</p>
                  ))}
                </div>
                {message.role === 'assistant' && message.citations.length > 0 ? (
                  <p className="sc-taifu-cites">
                    <span className="sc-taifu-citeslabel">依据</span>
                    {uniqueCitations(message.citations).map((citation) => (
                      <Link key={citation.href} to={citation.href} className="sc-taifu-cite">
                        {citation.label}
                      </Link>
                    ))}
                  </p>
                ) : null}
              </div>
            ))}

            {pending ? <p className="sc-taifu-hint">太傅正在看你的记录…</p> : null}
            {notice ? <p className="sc-taifu-notice">{notice}</p> : null}
            {sendError ? (
              <p className="sc-taifu-hint is-error" role="alert">
                {sendError}
              </p>
            ) : null}
            {meta ? (
              <p className="sc-taifu-hint">
                本次读取 {meta.materials} 段站内记录
                {meta.dropped > 0 ? `，已丢弃 ${meta.dropped} 条无依据引用` : ''}
                {meta.added > 0 ? `，记住 ${meta.added} 条新事实` : ''}
              </p>
            ) : null}
            {meta !== null && meta.materials === 0 ? (
              <p className="sc-taifu-shortcuts">
                <Link to="/">去上传简历</Link>
                <Link to="/practice">先做几道练习</Link>
                <Link to="/report">去看诊断报告</Link>
              </p>
            ) : null}

            {/* r81：长期记忆必须可查看、可删除 —— 否则用户不知道太傅「记住了自己什么」。 */}
            <div className="sc-taifu-memo">
              <button
                type="button"
                className="sc-taifu-linkbtn"
                aria-expanded={memoriesOpen}
                onClick={() => setMemoriesOpen((value) => !value)}
              >
                {memoriesOpen ? '收起记忆' : memoriesLabel(memories)}
              </button>
              {memoriesOpen ? (
                memoriesStatus === 'loading' ? (
                  <p className="sc-taifu-hint">正在读取记忆…</p>
                ) : memoriesStatus === 'error' ? (
                  <div className="sc-taifu-error" role="alert">
                    <p>{memoriesError}</p>
                    <button
                      type="button"
                      className="sc-taifu-textbtn"
                      onClick={() => void loadMemories()}
                    >
                      重试
                    </button>
                  </div>
                ) : memories !== null && memories.length === 0 ? (
                  <p className="sc-taifu-hint">
                    还没记住任何事。你明确说过的限制与偏好（例如「只有周末有空」）会被记住，
                    跨对话有效，随时可以忘掉。
                  </p>
                ) : (
                  <>
                    <ul className="sc-taifu-memolist">
                      {(memories ?? []).map((item) => (
                        <li key={item.id}>
                          <span className="sc-taifu-memotext">{item.content}</span>
                          <button
                            type="button"
                            className="sc-taifu-linkbtn"
                            onClick={() => void forgetOne(item.id)}
                            disabled={forgetting}
                          >
                            忘掉
                          </button>
                        </li>
                      ))}
                    </ul>
                    <button
                      type="button"
                      className="sc-taifu-linkbtn"
                      onClick={() => void forgetAll()}
                      disabled={forgetting}
                    >
                      {forgetArmed ? '再点一次全部忘掉' : '全部忘掉'}
                    </button>
                  </>
                )
              ) : null}
              {memoriesError && memoriesStatus === 'ready' ? (
                <p className="sc-taifu-hint is-error" role="alert">
                  {memoriesError}
                </p>
              ) : null}
            </div>
          </div>

          <form className="sc-taifu-composer" onSubmit={submit}>
            <input
              ref={inputRef}
              type="text"
              value={question}
              maxLength={TAIFU_QUESTION_MAX + 20}
              placeholder="问太傅，比如「我先补什么」"
              aria-label="问太傅"
              disabled={pending}
              onChange={(event) => setQuestion(event.target.value)}
            />
            <button type="submit" disabled={!canSend(question, pending)}>
              发送
            </button>
          </form>
          <p className="sc-taifu-foot">
            只读：不改你的画像、报告或计划，也不会自动投递。
            {thread.length > 0 ? (
              <button
                type="button"
                className="sc-taifu-linkbtn"
                onClick={() => void clearThread()}
                disabled={clearing}
              >
                {clearArmed ? '再点一次清空' : '清空对话'}
              </button>
            ) : null}
          </p>
        </div>
      ) : null}
    </>
  )
}
