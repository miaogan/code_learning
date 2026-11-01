import type { KeyboardEvent } from 'react'

export interface SegTabItem {
  key: string
  label: string
}

export interface SegTabsProps {
  tabs: SegTabItem[]
  active: string
  onChange: (key: string) => void
  /** 无障碍组名；缺省保持既有文案「原版与润色版切换」（练习页传「练习与错题本切换」）。 */
  ariaLabel?: string
}

/** 分段 Tab：高 40（DESIGN §0.2 `--sev-tab-h`），容器底 inset，选中项抬到 raised。
 *  键盘：←/→ 在项间移动，Home/End 跳到首尾（沿用 tablist 惯例）。 */
export function SegTabs({ tabs, active, onChange, ariaLabel = '原版与润色版切换' }: SegTabsProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const nextIndex = event.key === 'ArrowRight'
      ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft'
        ? (index - 1 + tabs.length) % tabs.length
        : event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? tabs.length - 1
            : -1
    if (nextIndex < 0) return
    event.preventDefault()
    onChange(tabs[nextIndex].key)
  }

  return (
    <div className="sc-seg-tabs" role="tablist" aria-label={ariaLabel}>
      {tabs.map((tab, index) => {
        const selected = tab.key === active
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            id={`sc-seg-tab-${tab.key}`}
            aria-selected={selected}
            aria-controls={`sc-seg-panel-${tab.key}`}
            tabIndex={selected ? 0 : -1}
            className={`sc-seg-tab${selected ? ' is-active' : ''}`}
            onClick={() => onChange(tab.key)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}
