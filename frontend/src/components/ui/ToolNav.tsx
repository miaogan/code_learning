import { Fragment, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

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
  /** 组标题；缺省「工具」（DESIGN r3 §1.1）。 */
  label?: string
  /**
   * `vertical` = 侧栏 240（DESIGN r3 §1.1 主形态）；
   * `horizontal` = <1024 收起侧栏后的顶部 40 高工具条（同一份 items，不给下游再造一遍）。
   */
  orientation?: 'vertical' | 'horizontal'
}

const itemClasses = (active: boolean): string =>
  active ? 'sc-toolnav-item is-active' : 'sc-toolnav-item'

const isActive = (pathname: string, to: string): boolean =>
  // 学习模块有子页面（`/learn/:chapterId`），只判全等会让文章页的侧栏失去高亮。
  pathname === to || pathname.startsWith(`${to}/`)

/**
 * 侧栏「工具」组（r3 新增；r126 改多级菜单）。
 *
 * 边界：
 * 1. **不混进 5 步线性流程**——工具页不是流程中的一步，塞进 Stepper 会让「当前步」语义失真；
 * 2. 当前项样式复用 Stepper 的 current 态（`--accent` 文字 + 左 2px 竖条 + `--accent-tint` 底）；
 * 3. 只用 `useLocation()` 判当前项（不读 state、不新增全局 store），与 `Stepper` 的判定口径一致；
 * 4. 分组默认收起，当前项所在组自动展开；手动展开/收起是组件内临时 state（会话级，
 *    不进 localStorage——侧栏分组次序由代码定死，记忆展开态的价值低于多一份存储）。
 */
export function ToolNav({ items, groups, label = '工具', orientation = 'vertical' }: ToolNavProps) {
  const { pathname } = useLocation()

  if (orientation === 'horizontal') {
    // 顶部工具条保持平铺：分组折叠在 40 高的横条上没有意义，横条自身横向滚动。
    const flat = groups ? groups.flatMap((group) => group.items) : (items ?? [])
    return (
      <nav className="sc-toolnav is-horizontal" aria-label={label}>
        <span className="sc-nav-label">{label}</span>
        {flat.map((item) => (
          <Link
            key={item.key}
            to={item.to}
            className={itemClasses(isActive(pathname, item.to))}
            aria-current={isActive(pathname, item.to) ? 'page' : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    )
  }

  if (groups && groups.length > 0) {
    return (
      <nav className="sc-toolnav is-vertical is-grouped" aria-label={label}>
        <span className="sc-nav-label">{label}</span>
        {groups.map((group) => (
          <CollapsibleGroup key={group.key} group={group} pathname={pathname} />
        ))}
      </nav>
    )
  }

  const flat = items ?? []
  if (flat.length === 0) return null
  return (
    <nav className="sc-toolnav is-vertical" aria-label={label}>
      <span className="sc-nav-label">{label}</span>
      {flat.map((item) => (
        <Link
          key={item.key}
          to={item.to}
          className={itemClasses(isActive(pathname, item.to))}
          aria-current={isActive(pathname, item.to) ? 'page' : undefined}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  )
}

/** 单个折叠组：默认收起；当前项落在组内时强制展开（渲染期推导，不占额外 state）。 */
function CollapsibleGroup({
  group,
  pathname,
}: {
  group: ToolNavGroup
  pathname: string
}) {
  // 手动展开只记「被用户点开过」的组 key；含当前项的组无论手动与否都展开。
  const [opened, setOpened] = useState<string[]>([])
  const containsActive = group.items.some((item) => isActive(pathname, item.to))
  const expanded = containsActive || opened.includes(group.key)

  const toggle = (): void => {
    setOpened((prev) =>
      prev.includes(group.key) ? prev.filter((key) => key !== group.key) : [...prev, group.key],
    )
  }

  return (
    <Fragment>
      <button
        type="button"
        className={containsActive ? 'sc-toolnav-group is-active' : 'sc-toolnav-group'}
        onClick={toggle}
        aria-expanded={expanded}
        aria-controls={`sc-toolnav-group-${group.key}`}
      >
        <span className="sc-toolnav-group-label">{group.label}</span>
        <span className="sc-toolnav-chevron" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
      </button>
      {expanded ? (
        <div className="sc-toolnav-group-body" id={`sc-toolnav-group-${group.key}`}>
          {group.items.map((item) => (
            <Link
              key={item.key}
              to={item.to}
              className={itemClasses(isActive(pathname, item.to))}
              aria-current={isActive(pathname, item.to) ? 'page' : undefined}
            >
              {item.label}
            </Link>
          ))}
        </div>
      ) : null}
    </Fragment>
  )
}
