import type { RunKind, RunSummary } from '../api/types'

/**
 * 成绩趋势折线图的**纯函数层**（分组 / 排序 / 坐标投影），无 DOM、无请求。
 *
 * 口径：面试均分是 0–10、笔试总分是 0–100，**两种量纲永不共轴**，
 * 因此按 `kind` 分成两张独立的小图，序列的 `max` 由类型决定（不是前端二次统计分数）。
 */
export const TREND_META: Record<RunKind, { title: string; max: number; unit: string }> = {
  interview: { title: '模拟面试 · 均分', max: 10, unit: '/10' },
  exam: { title: '模拟笔试 · 总分', max: 100, unit: '/100' },
}

/**
 * 目标线（r64）：**产品设定的比对刻度**，不是市场统计、也不是招聘分数线。
 * 面试满分 10 取 7、笔试满分 100 取 75，都相当于 70% 分；
 * 将来若有真实口径，只改这一个常量，两张图的线、图注与文案会一起变。
 */
export const TREND_TARGET: Record<RunKind, number> = { interview: 7, exam: 75 }

/** 目标线状态：给图注用的一句中文 + 可读的差值，页面不自己算。 */
export interface TargetStatus {
  target: number
  /** 最新 − 目标，保留 1 位；没有计分记录时为 null（不把「没成绩」当 0 分差）。 */
  gap: number | null
  text: string
}

/** 最新一次相对目标线的位置：超出 / 正好 / 还差 / 暂无记录，四种出口都有中文说明。 */
export function targetStatus(series: TrendSeries): TargetStatus {
  const target = TREND_TARGET[series.kind]
  if (series.latest === null) {
    return {
      target,
      gap: null,
      text: `目标 ${scoreText(target)}${series.unit}：暂无计分记录，先完成一次测评`,
    }
  }
  const gap = round1(series.latest - target)
  if (gap === 0) {
    return { target, gap, text: `最新正好达到目标 ${scoreText(target)}${series.unit}` }
  }
  if (gap > 0) {
    return { target, gap, text: `最新超出目标 ${scoreText(gap)}${series.unit}` }
  }
  return { target, gap, text: `最新距目标还差 ${scoreText(Math.abs(gap))}${series.unit}` }
}

export interface TrendPoint {
  id: string
  score: number
  /** 横轴短标签 `MM-DD`；`created_at` 不可解析时原样给出前 10 个字符。 */
  label: string
  /** 原始 ISO 时间（只用于 tooltip / aria，不参与排序——顺序由服务端倒序反推）。 */
  created_at: string
}

export interface TrendSeries {
  kind: RunKind
  title: string
  max: number
  unit: string
  /** **由旧到新**（输入是服务端时间倒序，这里只反序，不重排）。 */
  points: TrendPoint[]
  latest: number | null
  /** 同类型上一次的分数（不足两次为 null）。 */
  previous: number | null
  /** 最新 − 上一次，保留 1 位；不足两次为 null。 */
  delta: number | null
}

function round1(value: number): number {
  return Math.round(value * 10) / 10
}

/** `created_at` 是 UTC ISO8601，短标签按本机时区到「日」；解析失败保留原串前 10 个字符。 */
function shortLabel(createdAt: string): string {
  const date = new Date(createdAt)
  if (Number.isNaN(date.getTime())) return createdAt.slice(0, 10)
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** 文本分数：整数不带 `.0`，否则 1 位小数（与 TrendTable 的 `trimmed` 同一规则）。 */
export function scoreText(score: number): string {
  const value = round1(score)
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

/**
 * 某类型的折线序列：只保留已计分的行（`score === null` 无法落点，不伪造 0），
 * 并把服务端的倒序翻成时间升序（横轴从左到右才是「从旧到新」）。
 */
export function buildSeries(rows: RunSummary[], kind: RunKind): TrendSeries {
  const meta = TREND_META[kind]
  const points = rows
    .filter((row) => row.kind === kind && row.score !== null && Number.isFinite(row.score))
    .map((row) => ({
      id: row.id,
      score: row.score as number,
      label: shortLabel(row.created_at),
      created_at: row.created_at,
    }))
    .reverse()

  const latest = points.length > 0 ? points[points.length - 1].score : null
  const previous = points.length > 1 ? points[points.length - 2].score : null
  const delta = latest !== null && previous !== null ? round1(latest - previous) : null

  return { kind, title: meta.title, max: meta.max, unit: meta.unit, points, latest, previous, delta }
}

export interface ChartDot {
  x: number
  y: number
  score: number
  label: string
  id: string
}

export interface ChartTick {
  value: number
  y: number
  label: string
}

export interface ChartGeometry {
  width: number
  height: number
  padX: number
  padY: number
  dots: ChartDot[]
  /** 折线路径；点数 < 2 时为空串（单点只画圆点，不连线）。 */
  path: string
  /** 纵轴刻度：上限 / 中值 / 0（从下到上不必排序，组件按 `label` 渲染）。 */
  yTicks: ChartTick[]
  /** 目标线的分数值（见 `TREND_TARGET`）。 */
  target: number
  /** 目标线的画布纵坐标，口径与 `dots` 完全一致。 */
  targetY: number
}

/**
 * 把序列投影到画布坐标：横轴按**第几次**等距（不做时间比例尺，避免稀疏日期挤在一起），
 * 纵轴按 `series.max` 归一；越界分数按 0–max 夹取（后端已 clamp，这里只防御脏数据）。
 */
export function chartGeometry(
  series: TrendSeries,
  width = 480,
  height = 180,
  padX = 32,
  padY = 22,
): ChartGeometry {
  const innerWidth = Math.max(0, width - padX * 2)
  const top = padY
  const bottom = height - padY
  const innerHeight = Math.max(0, bottom - top)
  const count = series.points.length

  const xOf = (index: number): number => {
    if (count <= 1) return padX + innerWidth / 2
    return padX + (index * innerWidth) / (count - 1)
  }

  const yOf = (score: number): number => {
    const ratio = series.max > 0 ? Math.min(1, Math.max(0, score / series.max)) : 0
    return bottom - ratio * innerHeight
  }

  const dots = series.points.map((point, index) => ({
    x: xOf(index),
    y: yOf(point.score),
    score: point.score,
    label: point.label,
    id: point.id,
  }))

  const path =
    dots.length < 2
      ? ''
      : `M ${dots.map((dot) => `${dot.x.toFixed(1)},${dot.y.toFixed(1)}`).join(' L ')}`

  const tickValues = [series.max, series.max / 2, 0]
  const yTicks = tickValues.map((value) => ({ value, y: yOf(value), label: scoreText(value) }))

  const target = TREND_TARGET[series.kind]
  const targetY = yOf(target)

  return { width, height, padX, padY, dots, path, yTicks, target, targetY }
}
