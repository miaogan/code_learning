import type { RunSummary } from '../../api/types'
import { settingsLine } from '../interview/chatModel'

/**
 * 历史行「本场设定」文本（AC-11）：面试行的设定由服务端投影 `RunSummary.interview_settings` 给出，
 * 旧记录（`null`）同字号同色显示「未记录设定」；笔试卷没有「本场设定」概念，返回 `null` 整行不渲染。
 * 文本一律经 `settingsLine`（唯一格式化入口），禁止在页面/组件里另拼一份，否则会出现
 * 「未记录设定 / undefined」三处漂移（TECHNICAL §重复风险-1）。
 */
export function settingsTextOf(row: RunSummary): string | null {
  if (row.kind !== 'interview') return null
  return settingsLine(row.interview_settings)
}
