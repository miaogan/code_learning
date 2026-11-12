/**
 * 打卡热力图（r84 §2）的纯函数层：把测评/练习记录投影成「7 行 × N 列」日历格子。
 *
 * 口径：
 * - 7 行 = 周一到周日（周一在第一行，国内习惯）；列从旧到新，**最后一列止于今天**
 *   （不做「整月对齐」，今天的格子永远在最右下方向可见）；
 * - 每格计数 = 当天记录条数（同一天多次也如实计入，热力图本来就是频次视图）；
 * - 色阶 0–4：0 无记录；1 = 1 次；2 = 2 次；3 = 3–4 次；4 = ≥5 次。
 *   阈值写死在 `heatLevel`，将来要调只动这一处；
 * - 解析失败的 `created_at` 忽略，不占格、不抛错。
 *
 * 纯函数无 DOM 无请求，`today` 由调用方注入以便测试。
 */

export interface HeatCell {
  /** 稳定 React key：日键。 */
  key: string
  /** 本机时区 YYYY-MM-DD。 */
  day: string
  /** 当天记录条数。 */
  count: number
  /** 色阶 0–4。 */
  level: number
  /** 是否晚于 today（补齐尾列时的空格子）。 */
  isFuture: boolean
}

export interface HeatCalendarView {
  cells: HeatCell[]
  /** 窗口内的记录总数。 */
  total: number
  /** 窗口内有记录的天数。 */
  activeDays: number
  weeks: number
}

const DAY_MS = 24 * 60 * 60 * 1000

function dayKey(date: Date): string {
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function heatLevel(count: number): number {
  if (count >= 5) return 4
  if (count >= 3) return 3
  if (count >= 2) return 2
  if (count >= 1) return 1
  return 0
}

export function heatCalendar(
  rows: readonly { created_at: string }[],
  today: Date = new Date(),
  weeks = 12,
): HeatCalendarView {
  const counts = new Map<string, number>()
  for (const row of rows) {
    const date = new Date(row.created_at)
    if (Number.isNaN(date.getTime())) continue
    const key = dayKey(date)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }

  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  // 本周一（getDay() 周日=0 → 周一偏移 (getDay()+6)%7）；窗口从该周再往前推 weeks-1 周。
  const weekOffset = (todayStart.getDay() + 6) % 7
  const lastWeekStart = todayStart.getTime() - weekOffset * DAY_MS
  const firstWeekStart = lastWeekStart - (weeks - 1) * 7 * DAY_MS

  const cells: HeatCell[] = []
  let total = 0
  let activeDays = 0
  const columnCount = weeks * 7
  for (let index = 0; index < columnCount; index += 1) {
    const time = firstWeekStart + index * DAY_MS
    const date = new Date(time)
    const key = dayKey(date)
    const isFuture = time > todayStart.getTime()
    const count = counts.get(key) ?? 0
    if (!isFuture && count > 0) {
      total += count
      activeDays += 1
    }
    cells.push({ key, day: key, count: isFuture ? 0 : count, level: isFuture ? 0 : heatLevel(count), isFuture })
  }

  return { cells, total, activeDays, weeks }
}
