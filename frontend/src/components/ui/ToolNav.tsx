import { Link, useLocation } from 'react-router-dom'
import { NavSection } from './NavSection'
import { isRouteActive } from '../../lib/navGroups'

export interface ToolNavItem {
  key: string
  label: string
  to: string
}

/** r126 多级菜单：工具项按语义折叠进分组，侧栏不再因条目增多而内部滚动。 */
export interface ToolNavGroup {
  key: string
  label: string
  items: ToolNavItem[]
}

export interface ToolNavProps {
  /** 平铺条目（horizontal 顶部工具条 / 未分组场景）。 */
  items?: ToolNavItem[]
  /** 分组条目（vertical 侧栏形态）；给出时忽略 `items`，按折叠分组渲染。 */
  groups?: ToolNavGroup[]
  /** 组标题；缺省「工具」（DESIGN r3 §1.1）。传空串可隐藏（外层 NavSection 已承担标题）。 */
  label?: string
  /**
   * `vertical` = 侧栏 240（DESIGN r3 §1.1 主形态）；
   * `horizontal` = <1024 收起侧栏后的顶部 40 高工具条（同一份 items，不给下游再造一遍）。
   */
  orientation?: 'vertical' | 'horizontal'
}

const itemClasses = (active: boolean): string =>
  active ? 'sc-toolnav-item is-active' : 'sc-toolnav-item'

/**
 * 侧栏「工具」组（r3 新增；r126 改多级菜单，分组复用 NavSection 折叠）。
 *
 * 边界：
 * 1. **不混进 5 步线性流程**——工具页不是流程中的一步，塞进 Stepper 会让「当前步」语义失真；
 * 2. 当前项样式复用 Stepper 的 current 态（`--accent` 文字 + 左 2px 竖条 + `--accent-tint` 底）；
 * 3. 只用 `useLocation()` 判当前项（不读 state、不新增全局 store），与 `Stepper` 的判定口径一致。
 */
export function ToolNav({ items, groups, label = '工具', orientation = 'vertical' }: ToolNavProps) {
  const { pathname } = useLocation()

  if (orientation === 'horizontal') {
    // 顶部工具条保持平铺：分组折叠在 40 高的横条上没有意义，横条自身横向滚动。
    const flat = groups ? groups.flatMap((group) => group.items) : (items ?? [])
    return (
      <nav className="sc-toolnav is-horizontal" aria-label={label || '工具'}>
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

  if (groups && groups.length > 0) {
    return (
      <nav className="sc-toolnav is-vertical is-grouped" aria-label={label || '工具'}>
        {label ? <span className="sc-nav-label">{label}</span> : null}
        {groups.map((group) => (
          <NavSection
            key={group.key}
            sectionId={`tool-group-${group.key}`}
            label={group.label}
            activeInside={group.items.some((item) => isRouteActive(pathname, item.to))}
          >
            {group.items.map((item) => (
              <Link
                key={item.key}
                to={item.to}
                className={itemClasses(isRouteActive(pathname, item.to))}
                aria-current={isRouteActive(pathname, item.to) ? 'page' : undefined}
              >
                {item.label}
              </Link>
            ))}
          </NavSection>
        ))}
      </nav>
    )
  }

  const flat = items ?? []
  if (flat.length === 0) return null
  return (
    <nav className="sc-toolnav is-vertical" aria-label={label || '工具'}>
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
