import { Link, useLocation } from 'react-router-dom'

export interface ToolNavItem {
  key: string
  label: string
  to: string
}

export interface ToolNavProps {
  items: ToolNavItem[]
  /** 组标题；缺省「工具」（DESIGN r3 §1.1）。 */
  label?: string
  /**
   * `vertical` = 侧栏 240（DESIGN r3 §1.1 主形态）；
   * `horizontal` = <1024 收起侧栏后的顶部 40 高工具条（同一份 items，不给下游再造一遍）。
   */
  orientation?: 'vertical' | 'horizontal'
}

/**
 * 侧栏「工具」组（r3 新增）：成绩趋势 `/history`（此前无入口）与简历润色 `/polish`。
 *
 * 三条边界：
 * 1. **不混进 5 步线性流程**——润色/趋势不是流程中的一步，塞进 Stepper 会让「当前步」语义失真；
 * 2. 当前项样式复用 Stepper 的 current 态（`--accent` 文字 + 左 2px 竖条 + `--accent-tint` 底）；
 * 3. 只用 `useLocation()` 判当前项（不读 state、不新增全局 store），与 `Stepper` 的判定口径一致。
 */
export function ToolNav({ items, label = '工具', orientation = 'vertical' }: ToolNavProps) {
  const { pathname } = useLocation()
  if (items.length === 0) return null

  const classes = ['sc-toolnav', orientation === 'horizontal' ? 'is-horizontal' : 'is-vertical']

  return (
    <nav className={classes.join(' ')} aria-label={label}>
      <span className="sc-toolnav-label">{label}</span>
      {items.map((item) => {
        // 学习模块有子页面（`/learn/:chapterId`），只判全等会让文章页的侧栏失去高亮。
        const active = pathname === item.to || pathname.startsWith(`${item.to}/`)
        return (
          <Link
            key={item.key}
            to={item.to}
            className={active ? 'sc-toolnav-item is-active' : 'sc-toolnav-item'}
            aria-current={active ? 'page' : undefined}
          >
            {item.label}
          </Link>
        )
      })}
    </nav>
  )
}
