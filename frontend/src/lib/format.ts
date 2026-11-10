/** 数值 / 时长 / 字数格式化：等宽 + tabular 的展示规则集中在这里（DESIGN §0.7 约束）。 */

/** 得分：≤3 字符，整数不补小数位（"8"、"8.5"、"10"）。 */
export function formatScore(value: number): string {
  if (!Number.isFinite(value)) return '—'
  const clamped = Math.min(10, Math.max(0, value))
  return Number.isInteger(clamped) ? String(clamped) : clamped.toFixed(1)
}

/** 用时：正计时 mm:ss，上限显示 99:59（与计时环内文本宽度推导一致）。 */
export function formatElapsed(totalSeconds: number): string {
  const safe = Number.isFinite(totalSeconds) ? Math.max(0, Math.floor(totalSeconds)) : 0
  const capped = Math.min(99 * 60 + 59, safe)
  const minutes = Math.floor(capped / 60)
  const seconds = capped % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

/** 抽取字数：千分位 + 「字」。 */
export function formatChars(chars: number): string {
  if (!Number.isFinite(chars) || chars <= 0) return '0 字'
  return `${Math.floor(chars).toLocaleString('en-US')} 字`
}

/** 严重度只在文字层出现（颜色永不单独承载信息）。 */
export function severityLabel(severity: 'high' | 'medium' | 'low'): string {
  if (severity === 'high') return '高'
  if (severity === 'medium') return '中'
  return '低'
}

/**
 * 时间戳：服务端存的是 UTC ISO8601（`repository._now()`），展示按本机时区到分钟；
 * 解析失败时原样回显，不猜一个假时间。
 */
export function formatWhen(createdAt: string): string {
  const date = new Date(createdAt)
  if (Number.isNaN(date.getTime())) return createdAt
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
