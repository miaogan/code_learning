import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from 'react'

/**
 * 侧栏折叠分区（r126 迭代三）：**向右级联浮层**——大区头留在侧栏，
 * hover 停留 / 点击后向右浮出面板，二级分组在面板内再向右级联。
 * 浮层不挤占布局，侧栏永远只有三个大区头，无滚动条。
 *
 * 触发规范沿用迭代二的调研口径（NN/g / Baymard 2025 / Drupal 侧栏 UX 评审）：
 * - hover 展开必须带停留延迟（0.3–0.5s），移出带缓冲；
 * - 同级互斥（NavSectionGroup 协调），杜绝扫过时连环开合；
 * - 点击保底（触屏 / 键盘），且点击意图压过 hover；
 * - 触屏通过 `(hover: hover) and (pointer: fine)` 门控，不启用 hover。
 *
 * 与迭代二（下推手风琴）的差异：`activeInside` 不再强制展开面板——浮层盖在
 * 主区上方，常开会挡内容；改为大区头高亮 + 面板内条目高亮承载「当前位置」，
 * 点击面板内链接跳转后自动收起，点击面板外也收起（pinned 浮层的关闭通道）。
 */

const OPEN_DELAY_MS = 300
const CLOSE_DELAY_MS = 350

/** 仅在「有悬停能力的精确指针」设备上启用 hover 触发（触屏 / 触控板 Tap 模式不启用）。 */
const HOVER_CAPABLE =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(hover: hover) and (pointer: fine)').matches

interface NavHoverState {
  /** 当前 hover 展开的分区 id（互斥）；null = 无。 */
  openId: string | null
  /** 当前点击固定展开的分区 id（同样互斥，避免两个浮层叠加）；null = 无。 */
  pinnedId: string | null
  /** 请求 hover 展开某分区（同时收起其他 hover 展开的分区）。 */
  requestOpen: (id: string) => void
  /** 请求收起 hover 展开。 */
  requestClose: (id: string) => void
  /** 设置点击固定展开的分区（null = 全部收起）。 */
  setPinned: (id: string | null) => void
}

const NavHoverContext = createContext<NavHoverState>({
  openId: null,
  pinnedId: null,
  requestOpen: () => {},
  requestClose: () => {},
  setPinned: () => {},
})

export interface NavSectionGroupProps {
  children: ReactNode
}

/** 同级分区容器：提供 hover / 点击两种展开的互斥协调。同一侧栏的 NavSection 应包在同一容器内。 */
export function NavSectionGroup({ children }: NavSectionGroupProps) {
  const [openId, setOpenId] = useState<string | null>(null)
  const [pinnedId, setPinnedId] = useState<string | null>(null)
  return (
    <NavHoverContext.Provider
      value={{
        openId,
        pinnedId,
        requestOpen: (id) => setOpenId(id),
        requestClose: (id) => setOpenId((prev) => (prev === id ? null : prev)),
        setPinned: (id) => setPinnedId(id),
      }}
    >
      {children}
    </NavHoverContext.Provider>
  )
}

export interface NavSectionProps {
  /** 分区标题（流程 / 工具 / 设置；工具区二级为分组名）。 */
  label: string
  /** aria-controls 用；分区 key。 */
  sectionId: string
  /** 当前路由是否落在本区内——大区头高亮 + 面板内条目高亮，不再强制展开浮层。 */
  activeInside: boolean
  children: ReactNode
}

/**
 * 单个浮层分区：头部按钮常驻侧栏，面板 absolute 定位到头部右侧。
 *
 * - hover：进入分区停留 OPEN_DELAY_MS 展开；移出 CLOSE_DELAY_MS 收起（面板是
 *   wrapper 的 DOM 子节点，滑进面板不触发离开）；
 * - click：切换 pinned；pinned 面板在「点击面板内链接」或「点击面板外」时收起；
 * - 面板内二级 NavSection 复用同一实现，天然向右级联。
 */
export function NavSection({ label, sectionId, activeInside, children }: NavSectionProps) {
  const [hoverOpen, setHoverOpen] = useState(false)
  const { openId, pinnedId, requestOpen, requestClose, setPinned: setContextPinned } =
    useContext(NavHoverContext)
  const pinned = pinnedId === sectionId
  const wrapperRef = useRef<HTMLDivElement | null>(null)
  const openTimer = useRef<number | null>(null)
  const closeTimer = useRef<number | null>(null)

  // 互斥协调：别的分区请求 hover 展开时，收掉本区的 hover 态（pinned 不动）。
  useEffect(() => {
    if (openId !== null && openId !== sectionId) {
      setHoverOpen(false)
    }
  }, [openId, sectionId])

  // pinned 浮层盖在主区上：点击面板外任意处收起（仅在 pinned 期间挂监听）。
  useEffect(() => {
    if (!pinned) return
    const onDocPointerDown = (event: PointerEvent): void => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setContextPinned(null)
        setHoverOpen(false)
      }
    }
    document.addEventListener('pointerdown', onDocPointerDown)
    return () => document.removeEventListener('pointerdown', onDocPointerDown)
  }, [pinned, setContextPinned])

  useEffect(() => {
    return () => {
      if (openTimer.current !== null) window.clearTimeout(openTimer.current)
      if (closeTimer.current !== null) window.clearTimeout(closeTimer.current)
    }
  }, [])

  const clearTimers = (): void => {
    if (openTimer.current !== null) {
      window.clearTimeout(openTimer.current)
      openTimer.current = null
    }
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }

  const handleEnter = (): void => {
    if (!HOVER_CAPABLE) return
    clearTimers()
    openTimer.current = window.setTimeout(() => {
      setHoverOpen(true)
      requestOpen(sectionId)
    }, OPEN_DELAY_MS)
  }

  const handleLeave = (): void => {
    if (!HOVER_CAPABLE) return
    clearTimers()
    closeTimer.current = window.setTimeout(() => {
      setHoverOpen(false)
      requestClose(sectionId)
    }, CLOSE_DELAY_MS)
  }

  const expanded = pinned || hoverOpen

  const toggle = (): void => {
    // 点击意图优先：清掉在途 hover 计时；点收起时连 hover 态一起收，
    // 避免「点了收起但鼠标还悬着又被 hover 弹开」（Drupal 评审的打架场景）。
    // pinned 走 context 互斥——同一时刻最多一个点击固定的浮层。
    clearTimers()
    setHoverOpen(false)
    setContextPinned(pinned || hoverOpen ? null : sectionId)
  }

  // 面板内点链接（导航）→ 收起浮层；点面板内非链接区域不收。
  const handlePanelClick = (event: ReactMouseEvent<HTMLDivElement>): void => {
    if ((event.target as HTMLElement).closest('a')) {
      clearTimers()
      setContextPinned(null)
      setHoverOpen(false)
    }
  }

  return (
    <div
      className="sc-navsection"
      ref={wrapperRef}
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
    >
      <button
        type="button"
        className={activeInside ? 'sc-toolnav-group is-active' : 'sc-toolnav-group'}
        onClick={toggle}
        aria-expanded={expanded}
        aria-haspopup="true"
        aria-controls={`sc-navsection-${sectionId}`}
      >
        <span className="sc-toolnav-group-label">{label}</span>
        <span className="sc-toolnav-chevron" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
      </button>
      {expanded ? (
        <div
          className="sc-navsection-body"
          id={`sc-navsection-${sectionId}`}
          onClick={handlePanelClick}
        >
          {children}
        </div>
      ) : null}
    </div>
  )
}
