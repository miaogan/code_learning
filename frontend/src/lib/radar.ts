/**
 * r67 技术雷达展示层纯函数（页面零计算）：任务状态 / 阶段 / 进度文案、可否操作判定与数值格式化。
 *
 * 状态闭集与 `backend/app/services/radar/store.py` 的 `ACTIVE_STATUSES` / `TERMINAL_STATUSES` 一一对应；
 * 结论中文来自服务端 `verdict_label`（`rules.VERDICT_LABELS` 单源），前端不复制第二份词表。
 */

import type { RadarJobItem, RadarTechItem } from '../api/types'

/** 在途状态：`queued` / `running`，页面据此决定是否继续轮询。 */
export const ACTIVE_JOB_STATUSES = ['queued', 'running'] as const

const STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '生成中',
  succeeded: '已完成',
  adopted: '已扩充入库',
  discarded: '已废弃',
  failed: '生成失败',
}

const STAGE_LABELS: Record<string, string> = {
  chapter: '正在写学习章节',
  questions: '正在出练习题',
  done: '已生成完毕',
  failed: '已中止',
}

/** 越界状态不猜中文，原样回显（与「不编造」口径一致）。 */
export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage
}

export function isActiveJob(status: string): boolean {
  return ACTIVE_JOB_STATUSES.includes(status as (typeof ACTIVE_JOB_STATUSES)[number])
}

export function isTerminalJob(status: string): boolean {
  return !isActiveJob(status)
}

/** 进度文案：在途给「阶段 + 百分比」，终态给状态名（失败附原因）。 */
export function progressText(job: RadarJobItem): string {
  if (job.status === 'failed') {
    return job.error_message ? `${statusLabel('failed')}：${job.error_message}` : statusLabel('failed')
  }
  if (isActiveJob(job.status)) {
    const percent = Math.max(0, Math.min(100, Math.floor(job.progress)))
    return `${stageLabel(job.stage)} · ${percent}%`
  }
  return statusLabel(job.status)
}

/** 只有「生成完成且确有题过自检」才能扩充入库（互斥终态之一）。 */
export function canAdopt(job: RadarJobItem): boolean {
  return job.status === 'succeeded' && job.questions.length > 0
}

/** 生成中不能废弃（等它结束）；已完成 / 失败 / 已入库都可以作废草稿。 */
export function canDiscard(job: RadarJobItem): boolean {
  return !isActiveJob(job.status) && job.status !== 'discarded'
}

/** 自检丢弃原因 → 中文：与服务端 `generate.clean_question` 的 reason 码一一对应。 */
const DISCARD_REASON_LABELS: Record<string, string> = {
  options: '选项数量不合规（单选 / 多选 3–4 项，判断题恰好 2 项）',
  answer: '答案键不在选项里，或答案数量与题型不符',
  prompt: '题干少于 10 字',
  explanation: '解析少于 10 字',
  duplicate: '题干与前面的题重复',
}

const DISCARD_REASON_ORDER = ['options', 'answer', 'prompt', 'explanation', 'duplicate']

/** 丢弃明细：按固定顺序展开，未知原因原样回显（不猜中文）。 */
export function discardReasonLines(job: RadarJobItem): { reason: string; text: string; count: number }[] {
  const reasons = job.discarded_reasons ?? {}
  const known = DISCARD_REASON_ORDER.filter((reason) => (reasons[reason] ?? 0) > 0).map((reason) => ({
    reason,
    text: DISCARD_REASON_LABELS[reason],
    count: reasons[reason],
  }))
  const unknown = Object.keys(reasons)
    .filter((reason) => !DISCARD_REASON_ORDER.includes(reason) && reasons[reason] > 0)
    .map((reason) => ({ reason, text: reason, count: reasons[reason] }))
  return [...known, ...unknown]
}

/** 自检丢弃提示：没有丢弃就不打扰，有丢弃必须明示（透明度口径与 r46 / r52 一致）。 */
export function discardedNotice(job: RadarJobItem): string {
  if (job.discarded_count <= 0) return ''
  return `另有 ${job.discarded_count} 条题未通过自检，已丢弃且不入库（具体原因见下）。`
}

/** star 量级：1000 以上压成 1.2k，避免清单列过宽。 */
export function formatCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0'
  if (value < 1000) return String(Math.floor(value))
  return `${(value / 1000).toFixed(1)}k`
}

/** 7 日 star 增量：0 给「持平」，正数带 `+`（负数在仓储层已按 0 夹取）。 */
export function starDeltaText(delta: number): string {
  if (!Number.isFinite(delta) || delta <= 0) return '持平'
  return `+${formatCount(delta)}`
}

/** 四维读数一行化：数值越大越省力（学习成本）在界面必须带同一句注解。 */
export function dimensionText(item: RadarTechItem): string {
  return `相关度 ${item.relevance}/5 · 采用度 ${item.adoption}/5 · 成熟度 ${item.maturity}/5 · 学习成本 ${item.effort}/5`
}

/** 清单行副标题：方向 · 二级方向 · star 量级 + 增量。 */
export function techMetaText(item: RadarTechItem): string {
  const parts = [item.direction]
  if (item.sub_direction) parts.push(item.sub_direction)
  parts.push(`star ${formatCount(item.stars)}（7 日 ${starDeltaText(item.star_delta_7d)}）`)
  if (item.rule_based) parts.push('规则评估')
  if (item.suspect) parts.push('疑似刷 star，结论已降档')
  return parts.join(' · ')
}

/** 采集到的仓库链接只放行 http(s)：`javascript:` 等脏值一律当没有链接（不进 `href`）。 */
export function safeRepoUrl(url: string): string {
  const text = url.trim()
  return /^https?:\/\//i.test(text) ? text : ''
}

/** 这条摘要是否还值得翻：有足够拉丁字母且没有中文（与后端 `translate.needs_translation` 同口径）。 */
export function needsTranslation(summary: string): boolean {
  if (/[\u4e00-\u9fff]/.test(summary)) return false
  return (summary.match(/[A-Za-z]/g) ?? []).length >= 12
}

/** 展示用摘要：中文优先，没有译文时回退英文原文（原文永远不会被译文覆盖）。 */
export function summaryText(item: RadarTechItem): string {
  return item.summary_zh !== '' ? item.summary_zh : item.summary
}
