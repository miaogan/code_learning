import { useState, type ReactNode } from 'react'

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
 * 侧栏顶层折叠分区（r126 迭代）：流程 / 工具 / 设置 三个大区默认收起，
 * 侧栏任意时刻最多展开一个区，条目再多也不会撑出滚动条。
 *
 * - 展开判定与 ToolNav 分组同口径：activeInside 强制展开，手动开合是会话级 state；
 * - 样式复用 `.sc-toolnav-group`（组头）/ `.sc-navsection-body`（内容体）。
 */
export function NavSection({ label, sectionId, activeInside, children }: NavSectionProps) {
  const [opened, setOpened] = useState(false)
  const expanded = activeInside || opened

  const toggle = (): void => setOpened((prev) => !prev)

  return (
    <>
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
    </>
  )
}
