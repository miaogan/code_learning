/**
 * r67 技术雷达展示层纯函数（页面零计算）：任务状态 / 阶段 / 进度文案、可否操作判定与数值格式化。
 *
 * 状态闭集与 `backend/app/services/radar/store.py` 的 `ACTIVE_STATUSES` / `TERMINAL_STATUSES` 一一对应；
 * 结论中文来自服务端 `verdict_label`（`rules.VERDICT_LABELS` 单源），前端不复制第二份词表。
 */

import type { RadarJobItem, RadarTechItem, RadarWeekly } from '../api/types'
import { practiceHref } from './studyPlan'

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

/* ---------- r144 先锋信息流（aihot 式日期分组时间线）的纯函数层 ---------- */

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'] as const

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

/** assessed_at → 本地时区 HH:MM；解析失败返回空串（不猜时间）。 */
export function assessedTimeText(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  return `${pad2(at.getHours())}:${pad2(at.getMinutes())}`
}

interface ParsedDay {
  key: string
  /** aihot 口径：`11月19日 周四`。 */
  label: string
  today: boolean
}

function parsedDay(iso: string, now: Date): ParsedDay | null {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return null
  const key = `${at.getFullYear()}-${pad2(at.getMonth() + 1)}-${pad2(at.getDate())}`
  const todayKey = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`
  return {
    key,
    label: `${at.getMonth() + 1}月${at.getDate()}日 ${WEEKDAY_LABELS[at.getDay()]}`,
    today: key === todayKey,
  }
}

/** 一个日期分组：`key` 是 YYYY-MM-DD（未知时间落 `unknown` 组，不丢条目）。 */
export interface RadarDayGroup {
  key: string
  label: string
  items: RadarTechItem[]
}

/**
 * 按 `assessed_at` 的**本地日**把当前页条目分组（后端本就按评估时间倒序，
 * 分组只合并相邻同日条目，不重排——与接口顺序保持一致）。
 */
export function groupTechsByDay(
  items: readonly RadarTechItem[],
  now: Date = new Date(),
): RadarDayGroup[] {
  const groups: RadarDayGroup[] = []
  const index = new Map<string, RadarDayGroup>()
  for (const item of items) {
    const day = parsedDay(item.assessed_at, now)
    const key = day?.key ?? 'unknown'
    let group = index.get(key)
    if (group === undefined) {
      group = {
        key,
        label: day === null ? '时间未记录' : day.today ? `今天 · ${day.label}` : day.label,
        items: [],
      }
      index.set(key, group)
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups
}

/** 条目的标签行：方向 / 子方向（非空才出）+ 规则评估 / 疑似刷 star 两个状态标签。 */
export function techTagList(item: RadarTechItem): string[] {
  const tags = [item.direction, item.sub_direction]
    .map((tag) => tag.trim())
    .filter((tag) => tag !== '')
  if (item.rule_based) tags.push('规则评估')
  if (item.suspect) tags.push('疑似刷 star')
  return tags
}

/**
 * 当前页过滤：多词 AND，命中标题 / 中英摘要 / 方向 / 来源任一处。
 * 只作用于已取回的当前页（服务端分页），placeholder 必须写清「当前页」。
 */
export function matchesTechQuery(item: RadarTechItem, rawQuery: string): boolean {
  const query = rawQuery.trim().toLowerCase()
  if (query === '') return true
  const haystack = [
    item.name,
    item.summary,
    item.summary_zh,
    item.direction,
    item.sub_direction,
    item.source_key,
  ]
    .join('\n')
    .toLowerCase()
  return query
    .split(/\s+/)
    .filter((term) => term !== '')
    .every((term) => haystack.includes(term))
}

/* ---------- r146 分面计数与「为什么」 ---------- */

/** 结论四档的固定顺序：与服务端 `rules.VERDICTS` 同序，界面不因后端字典顺序抖动。 */
export const VERDICT_ORDER = ['must_learn', 'worth_knowing', 'watch', 'skip'] as const

const VERDICT_SHORT: Record<string, string> = {
  must_learn: '必学',
  worth_knowing: '选学',
  watch: '观望',
  skip: '跳过',
}

/**
 * 分面计数 → 摘要文案：`必学 8 · 选学 21 · 观望 18 · 跳过 10`。
 *
 * 缺档按 0 显示而不是省略——「观望 0」本身就是信息（本轮没有需要观望的），
 * 省略会让人以为是没算。
 */
export function verdictCountText(counts: Record<string, number> | undefined): string {
  return VERDICT_ORDER.map((verdict) => {
    const count = counts?.[verdict] ?? 0
    return `${VERDICT_SHORT[verdict]} ${count}`
  }).join(' · ')
}

/** 结论 chip 文案：带分面计数（`必学 8`）；`全部` 传总数。计数缺省时退回纯文案。 */
export function verdictChipLabel(label: string, count: number | undefined): string {
  return count === undefined ? label : `${label} ${count}`
}

/**
 * 清单头部计数文案（r146）：搜索 / 筛选 / 常态三种口径分开说。
 *
 * 三种口径混在一起最容易造成误读——「共 8 项」到底是清单只有 8 条，还是筛出来 8 条？
 * 所以筛选时同时给全量（`共 8 项 / 全部 57`），常态才顺带铺开四档分布。
 */
export function listCountText(input: {
  total: number
  pageCount: number
  allCount: number
  searching: boolean
  filtering: boolean
  counts?: Record<string, number>
}): string {
  const { total, pageCount, allCount, searching, filtering, counts } = input
  if (searching) return `本页 ${pageCount} / 共 ${total} 项`
  if (filtering) return `共 ${total} 项 / 全部 ${allCount}`
  return `共 ${total} 项 · ${verdictCountText(counts)}`
}

/**
 * 「为什么这么判」：折叠态只给第一条依据（岗位相关度），展开看全部。
 *
 * 取首条而不是拼四维，是因为 `rules.rule_assess` 的 `reasons` 顺序固定为
 * 相关度 → 采用度 → 成熟度 → 成本，首条恰是四档结论真正的判定依据。
 */
export function whyText(item: RadarTechItem): string {
  return item.reasons[0]?.trim() ?? ''
}

/* ---------- r146 走势线（借鉴 aihot 热点榜的 24h 走势，数据来自 radar_snapshots） ---------- */

/**
 * star 序列 → SVG polyline 的 `points` 串（宽 `width` 高 `height`，四周留 `pad`）。
 *
 * - 少于 2 个点返回空串：一个点画不出趋势，宁可不给也不画假线
 * - 全程同值时画在中线：flat 也是趋势（「没涨没跌」），且 min=max 时除零要防
 * - 坐标保留 1 位小数：polyline 属性串太长会拖慢渲染
 */
export function sparklinePoints(
  values: readonly number[],
  width = 64,
  height = 18,
  pad = 2,
): string {
  if (values.length < 2) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min
  const innerWidth = width - pad * 2
  const innerHeight = height - pad * 2
  const step = innerWidth / (values.length - 1)
  return values
    .map((value, index) => {
      const x = pad + index * step
      const y = span === 0 ? height / 2 : pad + innerHeight - ((value - min) / span) * innerHeight
      return `${Math.round(x * 10) / 10},${Math.round(y * 10) / 10}`
    })
    .join(' ')
}

/* ---------- r146 周报卡文案（滚动 7 天窗口，数据来自 /api/radar/weekly） ---------- */

/**
 * 周报卡一句话：新增对比上一周期 + 采集轮数；方向分布由页面渲染成可点芯片。
 *
 * 「持平」要如实说——上一周期 0、本周 0 时说「还没有新增条目」，不渲染成
 * 「比上一周期多 0 项」这种没信息量的句子。
 */
export function weeklyText(weekly: RadarWeekly): string {
  const delta =
    weekly.new_techs === weekly.prev_new_techs
      ? '与上一周期持平'
      : weekly.new_techs > weekly.prev_new_techs
        ? `比上一周期多 ${weekly.new_techs - weekly.prev_new_techs} 项`
        : `比上一周期少 ${weekly.prev_new_techs - weekly.new_techs} 项`
  const head =
    weekly.new_techs === 0 ? '还没有新增条目' : `新增 ${weekly.new_techs} 项（${delta}）`
  return `${head} · 采集 ${weekly.rounds} 轮`
}

/* ---------- r87 先锋 ↔ 国子监联动的纯函数层 ---------- */
/** 任务的方向读数：章节草稿优先，其次第一条题；都没有返回空串（不猜方向）。 */
export function jobDirection(job: RadarJobItem): string {
  const fromChapter = job.chapter?.direction ?? ''
  if (fromChapter.trim() !== '') return fromChapter.trim()
  const fromQuestion = job.questions[0]?.direction ?? ''
  return fromQuestion.trim()
}

/** 任务的二级方向读数：与方向同源（章节草稿优先，其次第一条题），空串 = 不聚焦。 */
export function jobSubDirection(job: RadarJobItem): string {
  const fromChapter = job.chapter?.sub_direction ?? ''
  if (fromChapter.trim() !== '') return fromChapter.trim()
  const fromQuestion = job.questions[0]?.sub_direction ?? ''
  return fromQuestion.trim()
}

/**
 * 国子监 → 演武的练习入口：**只有已扩充入库的任务**题目才真的在练习池里，
 * 其他状态（在途 / 已完成未入库 / 已废弃 / 失败）一律不给入口；推不出方向同样不给。
 */
export function jobPracticeHref(job: RadarJobItem): string {
  if (job.status !== 'adopted') return ''
  const direction = jobDirection(job)
  if (direction === '') return ''
  return practiceHref({ direction, sub_direction: jobSubDirection(job) })
}

/** 国子监 → 先锋的回链：带方向参数（先锋落为筛选）与技术名（未命中时提示用），第一页大概率能定位。 */
export function jobPioneerHref(job: RadarJobItem): string {
  const query = new URLSearchParams()
  query.set('tech', job.tech_slug)
  const name = job.tech_name.trim()
  if (name !== '') query.set('name', name)
  const direction = jobDirection(job)
  if (direction !== '') query.set('direction', direction)
  return `/pioneer?${query.toString()}`
}
