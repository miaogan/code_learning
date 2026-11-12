import type { Report, RunKind, RunSummary } from '../api/types'
import { DIRECTIONS } from './questionDirections'

/**
 * 能力雷达的**纯函数层**（七轴读数 + 参考基线 + 坐标投影），无 DOM、无请求，vitest 可直接测。
 *
 * 口径（必须与页面文案一致）：每根轴都是**测评证据的可核对读数**（最近一次得分、同类趋势、
 * 挑战题得分率、覆盖方向数、发挥波动、基础难度得分率、岗位技能达标率），不是对人的能力评级；
 * 参考均线 / 参考标杆是 `CAPABILITY_BASELINE` 里的产品参考刻度，**不是真实市场调研数据**。
 * 有真实统计后只改这一个常量。
 */
export type CapabilityKey =
  | 'technique'
  | 'depth'
  | 'breadth'
  | 'fundamentals'
  | 'stability'
  | 'learning'
  | 'readiness'

/** 轴标题，顺序即 `CAPABILITY_ORDER`（第一条轴在正上方，顺时针排列）。 */
export const CAPABILITY_TITLE: Record<CapabilityKey, string> = {
  technique: '技术力',
  depth: '深度',
  breadth: '广度',
  fundamentals: '基础扎实度',
  stability: '稳定度',
  learning: '学习力',
  readiness: '岗位匹配',
}

export const CAPABILITY_ORDER: CapabilityKey[] = [
  'technique',
  'depth',
  'breadth',
  'fundamentals',
  'stability',
  'learning',
  'readiness',
]

/** 两条参考线的刻度（0–1）：参考均线 50%、参考标杆 90%。 */
export const CAPABILITY_BASELINE = { average: 0.5, top: 0.9 } as const

/** 各轴口径的一句话说明（图例第二行，保证读数可被质疑时能查到来路）。 */
export const CAPABILITY_BASIS: Record<CapabilityKey, string> = {
  technique: '最近一次测评得分率',
  depth: '挑战难度题得分率',
  breadth: '测评覆盖的方向数',
  fundamentals: '基础 / 进阶题得分率',
  stability: '同类测评得分波动',
  learning: '同类测评相邻对比',
  readiness: '目标岗位技能达标率',
}

export interface CapabilityAxis {
  key: CapabilityKey
  title: string
  /** 0–1，只用于画图；事实看 `reading`。 */
  ratio: number
  /** 图例读数（可人工核对）。 */
  reading: string
  /** 口径说明。 */
  basis: string
  /** 是否有测评证据支撑（false ⇒ 该轴按 0 画，但图例明示「暂无测评数据」）。 */
  filled: boolean
}

export interface CapabilityInput {
  /** 最新报告；`null` = 还没生成过报告（深度 / 广度无从统计）。 */
  report: Report | null
  /** 成绩历史（服务端时间倒序）。 */
  runs: RunSummary[]
}

/** 满分：面试 /10、笔试 /100（与成绩趋势页的 `TREND_META` 同口径）。 */
const KIND_MAX: Record<RunKind, number> = { interview: 10, exam: 100 }

const EMPTY_READING = '暂无测评数据'

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

function finiteScore(score: number | null): number | null {
  return score !== null && Number.isFinite(score) ? score : null
}

/** 成绩文案：整数不带小数，其余保留 1 位。 */
function scoreText(score: number): string {
  return Number.isInteger(score) ? String(score) : score.toFixed(1)
}

interface AxisReading {
  ratio: number
  reading: string
}

/**
 * 技术力 = 最近一次有分的测评得分率。
 *
 * 服务端已按 `created_at` 倒序返回，这里**只取第一条有分记录、不自行排序**（与成绩趋势页同口径）；
 * 未计分的记录（`score === null`）跳过，不补 0。
 */
function techniqueOf(runs: RunSummary[]): AxisReading | null {
  for (const run of runs) {
    const score = finiteScore(run.score)
    if (score === null) continue
    const max = KIND_MAX[run.kind]
    if (!Number.isFinite(max) || max <= 0) continue
    const label = run.kind === 'interview' ? '面试' : '笔试'
    return { ratio: clamp01(score / max), reading: `最近一次${label} ${scoreText(score)}/${max}` }
  }
  return null
}

/**
 * 学习力 = 同类测评相邻对比中「提升或持平」的比例。
 *
 * 面试 /10 与笔试 /100 量纲不同，**只在同类内对比**；至少要有 1 次可比对的相邻记录，否则算无数据。
 */
function learningOf(runs: RunSummary[]): AxisReading | null {
  const chronological = [...runs].reverse()
  const byKind: Record<RunKind, number[]> = { interview: [], exam: [] }
  for (const run of chronological) {
    const score = finiteScore(run.score)
    if (score === null) continue
    byKind[run.kind].push(score)
  }

  let comparable = 0
  let nonDecrease = 0
  for (const scores of [byKind.interview, byKind.exam]) {
    for (let index = 1; index < scores.length; index += 1) {
      comparable += 1
      if (scores[index] >= scores[index - 1]) nonDecrease += 1
    }
  }
  if (comparable === 0) return null
  return {
    ratio: clamp01(nonDecrease / comparable),
    reading: `近 ${comparable} 次同类对比 · ${nonDecrease} 次提升或持平`,
  }
}

/** 深度 = 挑战难度分组的得分率（按 `difficulty` 含 `challenge` 的组聚合，每组只计一次）。 */
function depthOf(report: Report | null): AxisReading | null {
  const items = report?.weakness_map
  if (!Array.isArray(items)) return null
  const groups = items.filter((item) => item.difficulty.includes('challenge'))
  if (groups.length === 0) return null
  const total = groups.reduce((sum, item) => sum + item.total, 0)
  const wrong = groups.reduce((sum, item) => sum + item.wrong, 0)
  if (!Number.isFinite(total) || total <= 0) return null
  const ratio = clamp01((total - wrong) / total)
  return {
    ratio,
    reading: `挑战题得分率 ${Math.round(ratio * 100)}%（${total} 题）`,
  }
}

/** 广度 = 测评实际覆盖到的方向数 / 全库方向数（空方向不占一格）。 */
function breadthOf(report: Report | null): AxisReading | null {
  const items = report?.weakness_map
  if (!Array.isArray(items) || items.length === 0) return null
  const covered = new Set(
    items.map((item) => item.direction).filter((direction) => direction.trim() !== ''),
  )
  const denominator = Math.max(1, DIRECTIONS.length)
  if (covered.size === 0) return null
  return {
    ratio: clamp01(covered.size / denominator),
    reading: `覆盖 ${covered.size}/${denominator} 个方向`,
  }
}

/** 基础扎实度 = 基础 / 进阶难度分组的得分率（与「深度」互补，挑战题不计入本轴）。 */
function fundamentalsOf(report: Report | null): AxisReading | null {
  const items = report?.weakness_map
  if (!Array.isArray(items)) return null
  const groups = items.filter(
    (item) => item.difficulty.includes('basic') || item.difficulty.includes('intermediate'),
  )
  if (groups.length === 0) return null
  const total = groups.reduce((sum, item) => sum + item.total, 0)
  const wrong = groups.reduce((sum, item) => sum + item.wrong, 0)
  if (!Number.isFinite(total) || total <= 0) return null
  const ratio = clamp01((total - wrong) / total)
  return {
    ratio,
    reading: `基础 / 进阶题得分率 ${Math.round(ratio * 100)}%（${total} 题）`,
  }
}

/**
 * 稳定度 = 1 − 同类测评得分的变异系数（标准差 / 均值）。
 *
 * 面试 /10 与笔试 /100 量纲不同，**分别算变异系数再按样本数加权**；某一类不足 2 次无法算波动，
 * 不计入。波动越大越接近 0，完全没有波动时为 1（满分只代表「发挥稳定」，不代表分数高）。
 */
function stabilityOf(runs: RunSummary[]): AxisReading | null {
  const chronological = [...runs].reverse()
  const byKind: Record<RunKind, number[]> = { interview: [], exam: [] }
  for (const run of chronological) {
    const score = finiteScore(run.score)
    if (score === null) continue
    byKind[run.kind].push(score)
  }

  let samples = 0
  let weighted = 0
  for (const scores of [byKind.interview, byKind.exam]) {
    if (scores.length < 2) continue
    const mean = scores.reduce((sum, score) => sum + score, 0) / scores.length
    if (!Number.isFinite(mean) || mean <= 0) continue
    const variance =
      scores.reduce((sum, score) => sum + (score - mean) ** 2, 0) / scores.length
    const cv = Math.sqrt(variance) / mean
    samples += scores.length
    weighted += cv * scores.length
  }
  if (samples === 0) return null

  const cv = weighted / samples
  return {
    ratio: clamp01(1 - cv),
    reading: `同类 ${samples} 次 · 得分波动 ${Math.round(cv * 100)}%`,
  }
}

/**
 * 岗位匹配 = 目标岗位技能达标率（`role_fit.items` 的 `user_level / required` 均值）。
 *
 * 只统计 `required > 0` 的技能行；`gap <= 0` 记为达标。无报告 / 无岗位模型时算无数据。
 */
function readinessOf(report: Report | null): AxisReading | null {
  const fit = report?.role_fit
  const items = fit?.items
  if (!Array.isArray(items)) return null
  const scored = items.filter((item) => Number.isFinite(item.required) && item.required > 0)
  if (scored.length === 0) return null
  const sum = scored.reduce((total, item) => total + clamp01(item.user_level / item.required), 0)
  const met = scored.filter((item) => item.gap <= 0).length
  const role = fit?.target_role?.trim() ? fit.target_role.trim() : '目标岗位'
  return {
    ratio: clamp01(sum / scored.length),
    reading: `${role} · 技能达标 ${met}/${scored.length}`,
  }
}

/** 画像页的三份数据 → 7 条轴（缺数据时该轴为 0 且 `filled = false`，绝不伪造读数）。 */
export function capabilityAxes({ report, runs }: CapabilityInput): CapabilityAxis[] {
  const readings: Record<CapabilityKey, AxisReading | null> = {
    technique: techniqueOf(runs),
    depth: depthOf(report),
    breadth: breadthOf(report),
    fundamentals: fundamentalsOf(report),
    stability: stabilityOf(runs),
    learning: learningOf(runs),
    readiness: readinessOf(report),
  }

  return CAPABILITY_ORDER.map((key) => {
    const value = readings[key]
    return {
      key,
      title: CAPABILITY_TITLE[key],
      ratio: value === null ? 0 : clamp01(value.ratio),
      reading: value === null ? EMPTY_READING : value.reading,
      basis: CAPABILITY_BASIS[key],
      filled: value !== null,
    }
  })
}

/** 有测评证据的轴数（用于卡片副标题与空态判断）。 */
export function capabilityCoverage(axes: CapabilityAxis[]): number {
  return axes.filter((axis) => axis.filled).length
}

/**
 * 缺数据轴的补齐入口（纯函数，r76）：每条 `filled = false` 的轴给出 1–2 个站内跳转，
 * 指向能产出这份证据的模块（召对 / 科考 / 诊断报告）。跳转只补证据，**不预填任何读数**。
 */
export interface AxisFix {
  /** 按钮文案：说明这条跳转补的是哪份证据。 */
  label: string
  /** 站内路由。 */
  href: string
}

/** 各类别有分记录数（未计分记录不参与任何统计，与各轴口径一致）。 */
function scoredCounts(runs: RunSummary[]): { interview: number; exam: number } {
  const counts = { interview: 0, exam: 0 }
  for (const item of runs) {
    if (finiteScore(item.score) === null) continue
    counts[item.kind] += 1
  }
  return counts
}

/** 报告缺失时的补齐路径：已有测评记录 → 先生成报告；连记录都没有 → 先做一次科考。 */
function reportFixes(runs: RunSummary[]): AxisFix[] {
  const { interview, exam } = scoredCounts(runs)
  if (interview > 0 || exam > 0) {
    return [{ label: '已有测评记录，去生成诊断报告', href: '/report' }]
  }
  return [{ label: '去做一次科考', href: '/exam' }]
}

/** 同类测评不足 2 次（稳定度 / 学习力）时：缺哪类就补哪类，两类都缺给两个入口；
 * 已有 1 条有分记录的类说「再做一次」，一条都没有的类说「去做一次」。 */
function sameKindFixes(counts: { interview: number; exam: number }): AxisFix[] {
  const fixes: AxisFix[] = []
  if (counts.interview < 2) {
    fixes.push({
      label: counts.interview >= 1 ? '再做一次召对' : '去做一次召对',
      href: '/interview',
    })
  }
  if (counts.exam < 2) {
    fixes.push({
      label: counts.exam >= 1 ? '再做一次科考' : '去做一次科考',
      href: '/exam',
    })
  }
  return fixes
}

/**
 * 单条轴的补齐跳转：只对「暂无测评数据」的轴给出口；轴已有证据时返回空数组。
 * 判定条件与各轴统计函数**同源**（同一份数据要么算得出读数、要么给得出补法，不给第三种状态）。
 */
export function axisFixes(key: CapabilityKey, report: Report | null, runs: RunSummary[]): AxisFix[] {
  const counts = scoredCounts(runs)
  const hasScored = counts.interview > 0 || counts.exam > 0
  const weakness = report?.weakness_map
  const hasWeakness = Array.isArray(weakness) && weakness.length > 0
  switch (key) {
    case 'technique':
      return hasScored ? [] : [
        { label: '去做一次召对', href: '/interview' },
        { label: '去做一次科考', href: '/exam' },
      ]
    case 'depth':
      if (report === null) return reportFixes(runs)
      return hasWeakness && weakness.some((item) => item.difficulty.includes('challenge'))
        ? []
        : [{ label: '再做一次含挑战题的科考', href: '/exam' }]
    case 'fundamentals':
      if (report === null) return reportFixes(runs)
      return hasWeakness &&
        weakness.some(
          (item) => item.difficulty.includes('basic') || item.difficulty.includes('intermediate'),
        )
        ? []
        : [{ label: '再做一次含基础 / 进阶题的科考', href: '/exam' }]
    case 'breadth':
      if (report === null) return reportFixes(runs)
      return hasWeakness
        ? [{ label: '科考覆盖更多方向', href: '/exam' }]
        : [{ label: '去做一次科考', href: '/exam' }]
    case 'stability':
    case 'learning':
      return sameKindFixes(counts)
    case 'readiness': {
      if (report === null) return reportFixes(runs)
      const fit = report.role_fit
      if (fit === null) {
        return [{ label: '重新生成报告（画像需有目标岗位）', href: '/report' }]
      }
      const scored = fit.items.filter((item) => Number.isFinite(item.required) && item.required > 0)
      return scored.length > 0
        ? []
        : [{ label: '目标岗位未命中内置能力模型，可换岗位名后重新生成报告', href: '/report' }]
    }
  }
}

export interface RadarPoint {
  x: number
  y: number
}

/**
 * 把 0–1 的读数投影成多边形顶点：第一条轴在正上方（−90°），顺时针均分 360°。
 * `ratio` 越界按 0/1 夹取（防御脏数据，不抛错）。
 */
export function radarPoints(ratios: number[], cx: number, cy: number, radius: number): RadarPoint[] {
  const count = ratios.length
  if (count === 0 || radius <= 0) return []
  return ratios.map((ratio, index) => {
    const value = Number.isFinite(ratio) ? Math.min(1, Math.max(0, ratio)) : 0
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / count
    return {
      x: cx + Math.cos(angle) * radius * value,
      y: cy + Math.sin(angle) * radius * value,
    }
  })
}

/** 顶点 → 闭合多边形路径；不足 3 个点返回空串（组件据此不画填充区）。 */
export function radarPath(points: RadarPoint[]): string {
  if (points.length < 3) return ''
  const body = points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')
  return `M ${body} Z`
}

/** 顶点 → `points` 属性串（参考线多边形复用，避免组件里再写一遍 toFixed）。 */
export function radarPolygon(points: RadarPoint[]): string {
  return points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')
}
