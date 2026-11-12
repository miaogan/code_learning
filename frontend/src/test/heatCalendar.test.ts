import { describe, expect, it } from 'vitest'
import { heatCalendar, heatLevel } from '../lib/heatCalendar'

/** 固定「今天」= 2026-11-12（周四），窗口从它的本周一往回推。 */
const NOW = new Date(2026, 10, 12, 9, 0, 0)

function rowsOf(...dates: string[]): { created_at: string }[] {
  return dates.map((created_at) => ({ created_at }))
}

describe('heatLevel', () => {
  it('色阶阈值：0/1/2/3–4/≥5', () => {
    expect(heatLevel(0)).toBe(0)
    expect(heatLevel(1)).toBe(1)
    expect(heatLevel(2)).toBe(2)
    expect(heatLevel(3)).toBe(3)
    expect(heatLevel(4)).toBe(3)
    expect(heatLevel(5)).toBe(4)
    expect(heatLevel(99)).toBe(4)
  })
})

describe('heatCalendar', () => {
  it('格子总数 = 周数 × 7，最右列止于今天（未来的格子标 isFuture 且不计数）', () => {
    const view = heatCalendar([], NOW, 12)
    expect(view.cells).toHaveLength(12 * 7)
    const future = view.cells.filter((cell) => cell.isFuture)
    // 今天是周四：本周还剩周五到周日 3 天是未来。
    expect(future).toHaveLength(3)
    expect(view.total).toBe(0)
    expect(view.activeDays).toBe(0)
  })

  it('今天的记录落在最后一个非未来格子上', () => {
    const view = heatCalendar(rowsOf('2026-11-12T01:00:00Z'), NOW, 12)
    const last = view.cells[view.cells.length - 4] // 未来 3 天 → 今天的索引是 len-4
    expect(last.count).toBe(1)
    expect(last.level).toBe(1)
    expect(view.total).toBe(1)
    expect(view.activeDays).toBe(1)
  })

  it('同一天多条只热一格（计数累加，天数只算一天）', () => {
    const view = heatCalendar(
      rowsOf('2026-11-12T01:00:00Z', '2026-11-12T05:00:00Z', '2026-11-12T09:00:00Z'),
      NOW,
      12,
    )
    expect(view.activeDays).toBe(1)
    expect(view.total).toBe(3)
    const todayCell = view.cells[view.cells.length - 4]
    expect(todayCell.level).toBe(3) // 3–4 次 → 色阶 3
  })

  it('窗口外的旧记录不计入 total', () => {
    const view = heatCalendar(rowsOf('2026-01-01T01:00:00Z', '2026-11-12T01:00:00Z'), NOW, 12)
    expect(view.total).toBe(1)
  })

  it('脏日期串忽略不抛错', () => {
    const view = heatCalendar(rowsOf('garbage', ''), NOW, 12)
    expect(view.total).toBe(0)
  })

  it('首格是「今天所在周的周一往前推 11 周」的那一天（列从旧到新）', () => {
    const view = heatCalendar([], NOW, 4)
    const first = view.cells[0]
    // 2026-11-09（周一）− 3 周 = 2026-10-19
    expect(first.day).toBe('2026-10-19')
  })
})
