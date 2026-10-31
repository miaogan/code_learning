import type { ProfileMergeSummary } from '../../api/types'
import { Chip } from '../ui/Chip'

export interface MergeSummaryBarProps {
  summary: ProfileMergeSummary
}

/** 「本次合并」正文（纯函数：页面、上传摘要行与检查器共用同一口径）。 */
export function mergeSummaryText(summary: ProfileMergeSummary): string {
  return `新增 ${summary.added} 项能力 · ${summary.historical} 项转为历史 · 证据 +${summary.evidence_added}`
}

/**
 * 一次性合并摘要条（DESIGN §2.2 / §3 `MergeSummaryBar`，48 高）。
 * 数据只来自 `location.state`（「本次」语义，刷新即消失，不扩 `GET /profiles/latest` 契约）；
 * 纯信息条：无点击行为，历史项在页内自身分组里可展开，不做跨区跳转。
 */
export function MergeSummaryBar({ summary }: MergeSummaryBarProps) {
  return (
    <div className="sc-merge-bar" role="status" aria-live="polite">
      <span className="sc-merge-bar-label">本次合并</span>
      <span className="sc-merge-bar-text">{mergeSummaryText(summary)}</span>
      {summary.duplicate ? <Chip label="同一份简历 · 仍记为一次成长事件" /> : null}
    </div>
  )
}
