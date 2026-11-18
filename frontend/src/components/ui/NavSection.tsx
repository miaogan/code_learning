import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'

/**
 * 侧栏折叠分区的触发方式（r126 迭代二）：**hover 停留展开 + 点击保底**。
 *
 * 依据（NN/g《Menu Design》、Drupal 侧栏可用性评审、Baymard 2025 hover 菜单测试）：
 * - hover 展开必须带停留延迟（NN/g 建议 0.3–0.5s），否则鼠标路过就疯狂开合；
 * - 移出也要缓冲，让鼠标有时间滑进展开的内容区；
 * - 同一时刻只允许 hover 展开一个大区（互斥），否则纵向扫过侧栏时布局抖动严重；
 * - hover 对触屏 / 键盘不可用，点击必须保留为保底通道；点击意图（pinned）优先于 hover。
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
  /** 请求 hover 展开某分区（同时收起其他 hover 展开的分区）。 */
  requestOpen: (id: string) => void
  /** 请求收起 hover 展开。 */
  requestClose: (id: string) => void
}

const NavHoverContext = createContext<NavHoverState>({
  openId: null,
  requestOpen: () => {},
  requestClose: () => {},
})

export interface NavSectionGroupProps {
  children: ReactNode
}

/** 同级分区容器：提供 hover 展开的互斥协调。同一侧栏的 NavSection 应包在同一容器内。 */
export function NavSectionGroup({ children }: NavSectionGroupProps) {
  const [openId, setOpenId] = useState<string | null>(null)
  return (
    <NavHoverContext.Provider
      value={{
        openId,
        requestOpen: (id) => setOpenId(id),
        requestClose: (id) => setOpenId((prev) => (prev === id ? null : prev)),
      }}
    >
      {children}
    </NavHoverContext.Provider>
  )
}

export interface NavSectionProps {
  /** 分区标题（流程 / 工具 / 设置）。 */
  label: string
  /** aria-controls 用；分区 key。 */
  sectionId: string
  /** 当前路由是否落在本区内——是则强制展开（渲染期推导，刷新即正确）。 */
  activeInside: boolean
  children: ReactNode
}

/**
 * 侧栏折叠分区（r126 迭代二）：hover 停留展开，点击保底，路由激活强制展开。
 *
 * - 展开判定：`activeInside`（路由在区内）∨ `pinned`（用户点击过）∨ hover 互斥展开；
 * - hover：进入分区停留 OPEN_DELAY_MS 才展开；移出 CLOSE_DELAY_MS 后收起（滑进内容区不收）；
 * - 点击：清掉 hover 计时并切换 pinned——用户明确点收起时，hover 不会立刻又把它弹开。
 */
export function NavSection({ label, sectionId, activeInside, children }: NavSectionProps) {
  const [pinned, setPinned] = useState(false)
  const [hoverOpen, setHoverOpen] = useState(false)
  const { openId, requestOpen, requestClose } = useContext(NavHoverContext)
  const openTimer = useRef<number | null>(null)
  const closeTimer = useRef<number | null>(null)

  // 互斥协调：别的分区请求 hover 展开时，收掉本区的 hover 态（pinned 不动）。
  useEffect(() => {
    if (openId !== null && openId !== sectionId) {
      setHoverOpen(false)
    }
  }, [openId, sectionId])

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

  const expanded = activeInside || pinned || hoverOpen

  const toggle = (): void => {
    // 点击意图优先：清掉在途 hover 计时；点收起时连 hover 态一起收，避免「点了收起
    // 但鼠标还悬着又被 hover 弹开」（Drupal 评审里的 hover/click 打架场景）。
    clearTimers()
    setHoverOpen(false)
    setPinned((prev) => !(prev || hoverOpen || activeInside))
  }

  return (
    <div className="sc-navsection" onMouseEnter={handleEnter} onMouseLeave={handleLeave}>
      <button
        type="button"
        className={activeInside ? 'sc-toolnav-group is-active' : 'sc-toolnav-group'}
        onClick={toggle}
        aria-expanded={expanded}
        aria-controls={`sc-navsection-${sectionId}`}
      >
        <span className="sc-toolnav-group-label">{label}</span>
        <span className="sc-toolnav-chevron" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
      </button>
      {expanded ? (
        <div className="sc-navsection-body" id={`sc-navsection-${sectionId}`}>
          {children}
        </div>
      ) : null}
    </div>
  )
}
