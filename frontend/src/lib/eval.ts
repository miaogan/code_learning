/** r51 模型质量看板的纯展示逻辑：不取数、不排序服务端数据、不二次统计分母。 */
import type { EvalSummary } from '../api/types'

const KIND_LABELS: Record<string, string> = {
  success: '成功',
  timeout: '超时',
  connect: '连接失败',
  upstream: '上游错误',
  rejected: '被拒绝',
  malformed: '响应异常',
  schema_invalid: '结构校验失败',
  skipped: '能力未就绪',
}

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

/** 比例统一一位小数；越界值夹紧，非法值给占位符，避免出现 NaN%。 */
export function rateLabel(rate: number): string {
  if (!Number.isFinite(rate)) return '—'
  return `${(Math.max(0, Math.min(1, rate)) * 100).toFixed(1)}%`
}

export function latencyLabel(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms} ms`
}

export interface KindRow {
  kind: string
  label: string
  count: number
  share: number
}

/** 失败分类行：条数降序、平局按 kind 字典序（确定性）；share 分母恒为 summary.total。 */
export function kindRows(summary: EvalSummary): KindRow[] {
  return Object.entries(summary.by_kind)
    .map(([kind, count]) => ({
      kind,
      label: kindLabel(kind),
      count,
      share: summary.total > 0 ? count / summary.total : 0,
    }))
    .sort((a, b) => b.count - a.count || a.kind.localeCompare(b.kind))
}

export interface TrendRow {
  day: string
  label: string
  rate: number
  total: number
}

/** 趋势行只做日期切片，服务端已按 day 升序排好，前端不再排序。 */
export function trendRows(summary: EvalSummary): TrendRow[] {
  return summary.trend.map((point) => ({
    day: point.day,
    label: point.day.slice(5),
    rate: point.success_rate,
    total: point.total,
  }))
}

export function summaryNotice(summary: EvalSummary): string {
  if (summary.total === 0) return summary.notice || '暂无模型调用记录'
  return summary.notice
}
