import type { ProfileMergeSummary } from '../../api/types'

/** 「本次合并」正文（纯函数：页面、上传摘要行与检查器共用同一口径）。 */
export function mergeSummaryText(summary: ProfileMergeSummary): string {
  return `新增 ${summary.added} 项能力 · ${summary.historical} 项转为历史 · 证据 +${summary.evidence_added}`
}
