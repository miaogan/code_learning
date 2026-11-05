import type { ProfileMergeSummary } from '../../api/types'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { mergeSummaryText } from './mergeModel'

export interface MergeSummaryBarProps {
  summary: ProfileMergeSummary
  /** 历史能力 + 历史项目现存条数；≤0 → 不渲染入口按钮（AC-12：没有历史就没有死点击）。 */
  historyCount?: number
  /** 入口按钮 `aria-controls` 指向的页内历史分组 id（只含**实际存在**的容器，AC-11）。 */
  historyControls?: string[]
  /** 点击回调：展开历史分组 + 滚动进视口 + 焦点落到分组容器（由页面实现）。 */
  onViewHistory?: () => void
}

/**
 * 一次性合并摘要条（DESIGN §2.2 / §3 `MergeSummaryBar`，48 高）。
 * 数据只来自 `location.state`（「本次」语义，刷新即消失，不扩 `GET /profiles/latest` 契约）。
 *
 * r4 D-4：右侧多一个「查看历史能力项」入口槽（secondary / 40 高）。按钮槽**放回摘要条**
 * 而不是新组件，避免新增表面；有按钮时条高靠 `has-action` 把 padding 从 `sp-3` 降到 `sp-1`
 * 维持 48（`4 + 40 + 4`，不改任何既有 token）。
 */
export function MergeSummaryBar({
  summary,
  historyCount = 0,
  historyControls = [],
  onViewHistory,
}: MergeSummaryBarProps) {
  const showAction = historyCount > 0 && onViewHistory !== undefined
  const controls = historyControls.join(' ')

  return (
    <div className={showAction ? 'sc-merge-bar has-action' : 'sc-merge-bar'} role="status" aria-live="polite">
      <span className="sc-merge-bar-label">本次合并</span>
      <span className="sc-merge-bar-text">{mergeSummaryText(summary)}</span>
      {summary.duplicate ? <Chip label="同一份简历 · 仍记为一次成长事件" /> : null}
      {showAction ? (
        <Button
          variant="secondary"
          className="sc-merge-bar-action"
          aria-controls={controls === '' ? undefined : controls}
          onClick={onViewHistory}
        >
          查看历史能力项
        </Button>
      ) : null}
    </div>
  )
}
