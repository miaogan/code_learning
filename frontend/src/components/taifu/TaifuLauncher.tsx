import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport, type UIMessage } from 'ai'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import type {
  CSSProperties,
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from 'react'
import { Link, useLocation } from 'react-router-dom'

import { API_BASE, ApiError, api } from '../../api/client'
import type { TaifuCitation, TaifuFocus, TaifuMemoryItem } from '../../api/types'
import { onTaifuAsk } from '../../lib/taifuBridge'
import {
  TAIFU_QUESTION_MAX,
  TAIFU_SAMPLES,
  canSend,
  clampQuestion,
  parseReplyBlocks,
  splitBold,
  uniqueCitations,
} from '../../lib/taifuChat'
import {
  argsLine,
  cappedOf,
  noticeOf,
  partsToView,
  rowKeysOf,
  textOf,
} from '../../lib/taifuStream'
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

/** 焦点兜底文案：页面给了 label 就用它；没给就按类型说清是哪一条（不显示空白的「正在问：」）。 */
function focusText(focus: TaifuFocus): string {
  if (focus.kind === 'weakness') return `报告第 ${focus.index} 组`
  if (focus.kind === 'attempt') return focus.question_id
  return focus.anchor.length > 12 ? `${focus.anchor.slice(0, 12)}…` : focus.anchor
}

/** 行内加粗：只认 `**x**`，其余原样 —— 回答是纯文本，不为它引一个 Markdown 渲染器。 */
function inlineSpans(text: string) {
  return splitBold(text).map((span, index) =>
    span.bold ? <strong key={index}>{span.text}</strong> : <span key={index}>{span.text}</span>,
  )
}

/** 回答正文：段落 + 列表（`-` / `1.`）+ 行内加粗。列表符号不再裸露成正文。 */
function ReplyBody({ content, messageId }: { content: string; messageId: string }) {
  return (
    <>
      {parseReplyBlocks(content).map((block, index) => {
        const key = `${messageId}-${index}`
        if (block.kind !== 'list') {
          return <p key={key}>{inlineSpans(block.text ?? '')}</p>
        }
        const Tag = block.ordered ? 'ol' : 'ul'
        return (
          <Tag className="sc-taifu-points" key={key}>
            {(block.items ?? []).map((item, itemIndex) => (
              <li key={itemIndex}>{inlineSpans(item)}</li>
            ))}
          </Tag>
        )
      })}
    </>
  )
}

/**
 * 一条消息：正文、工具卡、依据与元信息都从 `parts` 推导。
 *
 * 历史消息由 `/thread` 转成只有 text part 的 UIMessage，引用走 `fallbackCitations`
 * （服务端历史里带 citations，但 UIMessage 的 data part 是有类型约束的，不为它放宽类型）。
 */
function MessageRow({
  message,
  rowKey,
  copiedKey,
  onCopy,
  fallbackCitations,
}: {
  message: UIMessage
  /** 列表行 key：重复 id 时带序号，"已复制"也按它区分，避免两条消息串台。 */
  rowKey: string
  copiedKey: string
  onCopy: (key: string, text: string) => void
  fallbackCitations?: TaifuCitation[]
}) {
  const view = partsToView(message.parts)
  const isUser = message.role === 'user'
  const text = textOf(message.parts)
  const notice = noticeOf(message.parts)
  const capped = cappedOf(message.parts)
  const citations =
    view.find((item) => item.kind === 'citations')?.items ?? fallbackCitations ?? []
  const meta = view.find((item) => item.kind === 'meta')

  return (
    <div className={isUser ? 'sc-taifu-msg is-user' : 'sc-taifu-msg'}>
      {view
        .filter((item) => item.kind === 'text' || item.kind === 'tool')
        .map((item) =>
          item.kind === 'text' ? (
            <div className="sc-taifu-msgtext" key={item.key}>
              <ReplyBody content={item.text} messageId={`${message.id}-${item.key}`} />
            </div>
          ) : (
            <div
              key={item.key}
              className={[
                'sc-tool',
                item.state === 'running' ? 'is-running' : '',
                item.state === 'done' && !item.ok ? 'is-miss' : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              <span className="sc-tool-head">
                <span className="sc-tool-dot" aria-hidden="true" />
                {item.label}
              </span>
              {argsLine(item.args) ? (
                <span className="sc-tool-args">{argsLine(item.args)}</span>
              ) : null}
              {item.state === 'running' ? (
                <span className="sc-tool-summary">正在读取…</span>
              ) : item.summary ? (
                <span className="sc-tool-summary">{item.summary}</span>
              ) : null}
            </div>
          ),
        )}

      {notice ? <p className="sc-taifu-notice">{notice}</p> : null}
      {capped ? (
        <p className="sc-taifu-hint">已达取料上限，先按读到的内容回答。</p>
      ) : null}

      {!isUser && text ? (
        <button type="button" className="sc-taifu-copy" onClick={() => onCopy(rowKey, text)}>
          {copiedKey === rowKey ? '已复制' : '复制'}
        </button>
      ) : null}

      {citations.length > 0 ? (
        <p className="sc-taifu-cites">
          <span className="sc-taifu-citeslabel">依据</span>
          {uniqueCitations(citations).map((citation) => (
            <Link key={citation.href} to={citation.href} className="sc-taifu-cite">
              {citation.label}
            </Link>
          ))}
        </p>
      ) : null}

      {meta ? (
        <p className="sc-taifu-hint">
          本次读取 {meta.materials} 段站内记录
          {meta.memoriesUsed > 0 ? `，参考 ${meta.memoriesUsed} 条记忆` : ''}
        </p>
      ) : null}
    </div>
  )
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

  const [threadStatus, setThreadStatus] = useState<ThreadStatus>('idle')
  const [threadError, setThreadError] = useState('')
  const [question, setQuestion] = useState('')
  const [sendError, setSendError] = useState('')
  /** 历史消息的引用：UIMessage 的 data part 有类型约束，历史里那几条单独按 id 存一份。 */
  const historyCitesRef = useRef<Record<string, TaifuCitation[]>>({})
  /** 这一问的上下文与回滚点：失败时按它收回问句、恢复输入框。 */
  const askRef = useRef<{ page: string; focus: TaifuFocus | null }>({
    page: location.pathname,
    focus: null,
  })
  const sendSnapshotRef = useRef<{ count: number; text: string } | null>(null)
  /** r82 焦点：从页面「问太傅」带过来的那一条；发送后保留，便于同一话题连续追问。 */
  const [focus, setFocus] = useState<{ value: TaifuFocus; label: string } | null>(null)

  // r83：请求体自己拼，不把 UIMessage 结构暴露给后端 —— 服务端契约仍是 {question, page, focus}，
  // 旧端点与流式端点共用同一个请求模型。
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `${API_BASE}/api/taifu/chat/stream`,
        prepareSendMessagesRequest: ({ messages: current }) => {
          const last = [...current].reverse().find((item) => item.role === 'user')
          return {
            body: {
              question: last ? textOf(last.parts) : '',
              page: askRef.current.page,
              focus: askRef.current.focus,
            },
          }
        },
      }),
    [],
  )

  const {
    messages,
    sendMessage,
    setMessages,
    status,
    stop,
  } = useChat({
    transport,
    onError: (err) => {
      // 失败不留半条对话：收回这句问话，把原文放回输入框让用户改。
      const snapshot = sendSnapshotRef.current
      sendSnapshotRef.current = null
      if (snapshot) {
        setMessages((prev) => prev.slice(0, snapshot.count))
        setQuestion(snapshot.text)
      }
      setSendError(err.message || '问太傅失败，请稍后重试')
    },
    onFinish: ({ message }) => {
      const snapshot = sendSnapshotRef.current
      sendSnapshotRef.current = null
      if (textOf(message.parts)) return
      // 没有正文（空档案 / 模型没生成出来）：服务端不落库，界面也不该留下这一问。
      setMessages((prev) => prev.slice(0, snapshot?.count ?? Math.max(0, prev.length - 2)))
      if (snapshot) setQuestion(snapshot.text)
    },
  })

  const pending = status === 'submitted' || status === 'streaming'
  const [copiedKey, setCopiedKey] = useState('')
  // 行 key 与消息一一对应：重复 id 追加序号，渲染与"已复制"都按它区分。
  const rowKeys = useMemo(() => rowKeysOf(messages), [messages])
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
      // 历史里只有正文 + 引用：正文转成 text part，引用单独存（见 historyCitesRef 的注释）。
      const cites: Record<string, TaifuCitation[]> = {}
      const seeded = data.messages.map((item) => {
        if (item.citations.length > 0) cites[item.id] = item.citations
        return {
          id: item.id,
          role: item.role,
          parts: [{ type: 'text', text: item.content }],
        } as UIMessage
      })
      historyCitesRef.current = cites
      setMessages(seeded)
      setThreadStatus('ready')
    } catch (error) {
      setThreadError(errorText(error))
      setThreadStatus('error')
    }
  }, [setMessages])

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
  // r82：焦点同源失效 —— 上一页的「第 3 组」带到下一页会问错对象，必须一起清掉。
  useEffect(() => {
    setOpen(false)
    setFocus(null)
  }, [location.pathname, location.hash])

  // r82：页面上的「问太傅」入口唤起浮窗。不自动发送：与示例问题同一交互（先填进输入框，用户可改）。
  useEffect(() => {
    return onTaifuAsk((ask) => {
      setOpen(true)
      setQuestion(ask.question)
      setFocus({ value: ask.focus, label: ask.label })
      setSendError('')
      // 面板刚展开时输入框还没挂载，等一帧再聚焦。
      window.setTimeout(() => inputRef.current?.focus(), 0)
    })
  }, [])

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
  // 新消息 / 等待态 / 展开记忆都把视图带到最底部。
  // r83：依赖整个 `messages` 而不是长度 —— 流式期间长度不变、内容一直在长，
  // 不跟着滚的话用户要手动拖滚动条才能看到正在生成的字。
  useEffect(() => {
    if (!open) return
    const body = bodyRef.current
    if (body === null) return
    body.scrollTop = body.scrollHeight
  }, [open, messages, pending, sendError, memoriesOpen, memories?.length])

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

  const send = useCallback(() => {
    const text = clampQuestion(question)
    if (!canSend(text, pending)) return
    // 上下文与回滚点在发车这一刻定格：流式途中切页面不会把「这一问」的焦点弄混。
    askRef.current = { page: location.pathname, focus: focus?.value ?? null }
    sendSnapshotRef.current = { count: messages.length, text }
    setQuestion('')
    setSendError('')
    sendMessage({ text })
  }, [focus, location.pathname, messages.length, pending, question, sendMessage])

  /** 复制回答原文（含列表符号与 `**`）：用户要的是能贴到别处的纯文本，不是渲染后的富文本。 */
  const copyMessage = useCallback(async (key: string, text: string) => {
    try {
      if (!navigator.clipboard) throw new Error('clipboard unavailable')
      await navigator.clipboard.writeText(text)
      setCopiedKey(key)
      window.setTimeout(() => {
        setCopiedKey((current) => (current === key ? '' : current))
      }, 2000)
    } catch {
      setSendError('复制失败，请手动选中回答文本')
    }
  }, [])

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
      setMessages([])
      historyCitesRef.current = {}
      setThreadStatus('ready')
    } catch (error) {
      setSendError(errorText(error))
    } finally {
      setClearing(false)
      setClearArmed(false)
    }
  }, [clearArmed, setMessages])

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    send()
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

          {/* r82：焦点必须可见、可取消 —— 否则用户不知道这一问带的是哪一条，也撤不掉。 */}
          {focus ? (
            <div className="sc-taifu-focus">
              <span className="sc-taifu-focuslabel">正在问</span>
              <span className="sc-taifu-focustext">{focus.label || focusText(focus.value)}</span>
              <button
                type="button"
                className="sc-taifu-linkbtn"
                onClick={() => setFocus(null)}
                aria-label="取消焦点，改问整体情况"
              >
                取消
              </button>
            </div>
          ) : null}

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

            {threadStatus === 'ready' && messages.length === 0 ? (
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

            {messages.map((message, index) => {
              // key 不能直接吃 `message.id`：服务端 id 撞了会让整列 React key 重复、
              // 「已复制」串台。`rowKeysOf` 对重复 id 追加序号，重复时显示两条而不是塌成一条。
              const rowKey = rowKeys[index] ?? message.id
              return (
                <MessageRow
                  key={rowKey}
                  rowKey={rowKey}
                  message={message}
                  copiedKey={copiedKey}
                  onCopy={(key, text) => void copyMessage(key, text)}
                  fallbackCitations={historyCitesRef.current[message.id]}
                />
              )
            })}

            {pending ? (
              <p className="sc-taifu-hint">
                太傅正在看你的记录…
                <button type="button" className="sc-taifu-linkbtn" onClick={stop}>
                  停止
                </button>
              </p>
            ) : null}
            {sendError ? (
              <div className="sc-taifu-error" role="alert">
                <p>{sendError}</p>
                <button type="button" className="sc-taifu-textbtn" onClick={() => setSendError('')}>
                  知道了
                </button>
              </div>
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
            {messages.length > 0 ? (
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
