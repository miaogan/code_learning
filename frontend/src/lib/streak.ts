/**
 * 学习连续性统计（r84 §3 / r138 口径修正）：streak（连续天数）+ 本周完成数。
 *
 * 口径约定：
 * - 「一天有记录」= 当天（**本机时区**）至少一次活跃：测评完成 / 演武作答 / 学堂阅读；
 *   r138 起由服务端 `/api/activity/days` 聚合三类并折算日键，不再只读战绩列表；
 * - streak 的锚点：今天有记录从今天往回数；今天没有但昨天有，**保留** streak
 *   （早上打开网页不该显示 0，否则用户每天早晨都会被劝退）；今天昨天都没有 → 0；
 * - 周口径周一为一周之始（国内习惯），weekDone 是「本周有记录的天数」，目标 7 只是
 *   展示刻度（x/7），不是产品指标。
 *
 * 纯函数无 DOM 无请求；日期串解析失败/空串直接忽略，不抛错。
 */

export interface StreakView {
  /** 连续有记录的天数（今天或昨天为锚点，见模块注释）。 */
  streakDays: number
  /** 今天是否已有记录。 */
  activeToday: boolean
  /** 本周（周一起算）有记录的天数，0–7。 */
  weekDone: number
  /** 本周展示刻度，恒 7。 */
  weekTarget: number
}

const DAY_MS = 24 * 60 * 60 * 1000
const DAY_KEY_RE = /^\d{4}-\d{2}-\d{2}$/

/** 本机时区的 YYYY-MM-DD 键。 */
function dayKey(date: Date): string {
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

/** ISO 串 → 本机时区日键；解析失败返回 null（调用方忽略）。 */
export function toDateKey(createdAt: string): string | null {
  const date = new Date(createdAt)
  if (Number.isNaN(date.getTime())) return null
  return dayKey(date)
}

/** r138 主入口：直接吃服务端聚合好的本地日键，脏串忽略。 */
export function computeStreakFromDays(
  dayKeys: readonly string[],
  now: Date = new Date(),
): StreakView {
  const days = new Set(dayKeys.filter((key) => DAY_KEY_RE.test(key)))

  const today = startOfDay(now)
  const activeToday = days.has(dayKey(today))
  const activeYesterday = days.has(dayKey(new Date(today.getTime() - DAY_MS)))

  let streakDays = 0
  if (activeToday || activeYesterday) {
    // 锚点：今天没练就从昨天起数（连续性保留一整天宽限）。
    let cursor = activeToday ? today.getTime() : today.getTime() - DAY_MS
    while (days.has(dayKey(new Date(cursor)))) {
      streakDays += 1
      cursor -= DAY_MS
    }
  }

  // 本周：周一为始。getDay() 周日=0 → 周一偏移 = (getDay()+6)%7。
  const weekOffset = (today.getDay() + 6) % 7
  const weekStart = today.getTime() - weekOffset * DAY_MS
  let weekDone = 0
  for (let index = 0; index <= weekOffset; index += 1) {
    if (days.has(dayKey(new Date(weekStart + index * DAY_MS)))) weekDone += 1
  }

  return { streakDays, activeToday, weekDone, weekTarget: 7 }
}

/** 兼容旧调用与测试：从带时间戳的行计算，仍按本机时区归一后走同一套统计。 */
export function computeStreak(
  rows: readonly { created_at: string }[],
  now: Date = new Date(),
): StreakView {
  const dayKeys = rows
    .map((row) => toDateKey(row.created_at))
    .filter((key): key is string => key !== null)
  return computeStreakFromDays(dayKeys, now)
}
