import { describe, expect, it } from 'vitest'
import { computeStreak, toDateKey } from '../lib/streak'

/** 固定「今天」= 2026-11-12（周四），避免用例跟着真实日期漂。 */
const NOW = new Date(2026, 10, 12, 9, 0, 0)

function rowsOf(...dates: string[]): { created_at: string }[] {
  return dates.map((created_at) => ({ created_at }))
}

describe('toDateKey', () => {
  it('把 ISO 串转成本机时区日键', () => {
    expect(toDateKey('2026-11-12T01:30:00Z')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('解析失败给 null（调用方忽略，不抛错）', () => {
    expect(toDateKey('not-a-date')).toBeNull()
    expect(toDateKey('')).toBeNull()
  })
})

describe('computeStreak', () => {
  it('今天有记录：从今天连续往回数', () => {
    const rows = rowsOf('2026-11-12T01:00:00Z', '2026-11-11T01:00:00Z', '2026-11-10T01:00:00Z')
    expect(computeStreak(rows, NOW)).toMatchObject({ streakDays: 3, activeToday: true })
  })

  it('今天没练但昨天练了：streak 保留（早晨打开不该看到 0）', () => {
    const rows = rowsOf('2026-11-11T01:00:00Z', '2026-11-10T01:00:00Z')
    expect(computeStreak(rows, NOW)).toMatchObject({ streakDays: 2, activeToday: false })
  })

  it('今天昨天都没练：streak 归 0', () => {
    const rows = rowsOf('2026-11-09T01:00:00Z', '2026-11-10T01:00:00Z')
    expect(computeStreak(rows, NOW)).toMatchObject({ streakDays: 0 })
  })

  it('同一天多条记录只算一天（按日去重）', () => {
    const rows = rowsOf('2026-11-12T01:00:00Z', '2026-11-12T08:00:00Z', '2026-11-12T15:00:00Z')
    const view = computeStreak(rows, NOW)
    expect(view.streakDays).toBe(1)
    expect(view.activeToday).toBe(true)
  })

  it('本周（周一起算）只数本周的天数：周四 → 周一到周四之间', () => {
    // 2026-11-12 是周四；本周一 = 11-09。
    const rows = rowsOf(
      '2026-11-08T01:00:00Z', // 上周日，不计入本周
      '2026-11-09T01:00:00Z', // 周一
      '2026-11-12T01:00:00Z', // 周四（今天）
    )
    const view = computeStreak(rows, NOW)
    expect(view.weekDone).toBe(2)
    expect(view.weekTarget).toBe(7)
  })

  it('空记录：全 0，不抛错', () => {
    expect(computeStreak([], NOW)).toMatchObject({ streakDays: 0, activeToday: false, weekDone: 0 })
  })

  it('脏日期串被忽略，不影响其余统计', () => {
    const rows = rowsOf('garbage', '2026-11-12T01:00:00Z')
    expect(computeStreak(rows, NOW)).toMatchObject({ streakDays: 1, activeToday: true })
  })
})
