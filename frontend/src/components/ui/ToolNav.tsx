import { Link, useLocation } from 'react-router-dom'
import { isRouteActive } from '../../lib/navGroups'

export interface ToolNavItem {
  key: string
  label: string
  to: string
}

export interface ToolNavProps {
  /** 平铺条目（顶部工具条 / 设置组）。 */
  items?: ToolNavItem[]
  /** 组标题；缺省「工具」（DESIGN r3 §1.1）。传空串可隐藏（外层已有标题）。 */
  label?: string
  /**
   * `horizontal` = 顶部工具条（<1024 收起侧栏后的主入口；r127 起桌面顶栏的
   * 工具导航由 App 的 `.sc-topnav` 直接渲染，分组语义用细分隔线表达，
   * 不再走 ToolNav 折叠）；
   * `vertical` = 侧栏形态（r127 起侧栏只剩流程 Stepper，此形态仅备用）。
   */
  orientation?: 'vertical' | 'horizontal'
}

const itemClasses = (active: boolean): string =>
  active ? 'sc-toolnav-item is-active' : 'sc-toolnav-item'

/**
 * 平铺工具导航（r3 新增；r126 短暂承担分组折叠，r127 回归单一职责——
 * 分组折叠/浮层已整体退役，工具入口上移到桌面顶栏 + 手机横条平铺）。
 *
 * 边界：
 * 1. **不混进 5 步线性流程**——工具页不是流程中的一步，塞进 Stepper 会让「当前步」语义失真；
 * 2. 当前项样式复用 Stepper 的 current 态（`--accent` 文字 + 左 2px 竖条 + `--accent-tint` 底）；
 * 3. 只用 `useLocation()` 判当前项（不读 state、不新增全局 store），与 `Stepper` 的判定口径一致。
 */
export function ToolNav({ items, label = '工具', orientation = 'vertical' }: ToolNavProps) {
  const { pathname } = useLocation()
  const flat = items ?? []
  if (flat.length === 0) return null

  return (
    <nav className={`sc-toolnav is-${orientation}`} aria-label={label || '工具'}>
      {label ? <span className="sc-nav-label">{label}</span> : null}
      {flat.map((item) => (
        <Link
          key={item.key}
          to={item.to}
          className={itemClasses(isRouteActive(pathname, item.to))}
          aria-current={isRouteActive(pathname, item.to) ? 'page' : undefined}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  )
}
