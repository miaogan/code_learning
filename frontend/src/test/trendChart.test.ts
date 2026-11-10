import { describe, expect, it } from 'vitest'
import type { RunSummary } from '../api/types'
import { TREND_META, buildSeries, chartGeometry, scoreText } from '../lib/trendChart'

/** 服务端口径：时间倒序（最新的在前）。 */
function run(
  id: string,
  kind: 'interview' | 'exam',
  score: number | null,
  createdAt: string,
): RunSummary {
  return { id, kind, score, shortfall_count: null, created_at: createdAt, interview_settings: null }
}

describe('buildSeries 分组与时间方向', () => {
  const rows: RunSummary[] = [
    run('i3', 'interview', 8, '2026-11-08T10:00:00Z'),
    run('e2', 'exam', 70, '2026-11-07T10:00:00Z'),
    run('i2', 'interview', 6.5, '2026-11-06T10:00:00Z'),
    run('e1', 'exam', null, '2026-11-05T10:00:00Z'),
    run('i1', 'interview', 7, '2026-11-04T10:00:00Z'),
  ]

  it('只取本类型的行，并翻成由旧到新', () => {
    const series = buildSeries(rows, 'interview')
    expect(series.points.map((point) => point.id)).toEqual(['i1', 'i2', 'i3'])
    expect(series.points.map((point) => point.score)).toEqual([7, 6.5, 8])
  })

  it('未计分的行不落点（不补 0）', () => {
    const series = buildSeries(rows, 'exam')
    expect(series.points.map((point) => point.id)).toEqual(['e2'])
    expect(series.latest).toBe(70)
    expect(series.previous).toBeNull()
    expect(series.delta).toBeNull()
  })

  it('最新 / 上一次 / 差值都取自同类型相邻两次', () => {
    const series = buildSeries(rows, 'interview')
    expect(series.latest).toBe(8)
    expect(series.previous).toBe(6.5)
    expect(series.delta).toBe(1.5)
    expect(series.max).toBe(TREND_META.interview.max)
    expect(series.unit).toBe('/10')
  })

  it('横轴标签是 MM-DD；不可解析的时间原样截断', () => {
    const series = buildSeries(
      [run('x', 'exam', 50, 'not-a-date-value')],
      'exam',
    )
    expect(series.points[0].label).toBe('not-a-date')
  })
})

describe('chartGeometry 投影', () => {
  it('满分落在上边距、0 分落在下边距，单点居中', () => {
    const series = buildSeries(
      [run('a', 'interview', 10, '2026-11-08T10:00:00Z')],
      'interview',
    )
    const geometry = chartGeometry(series, 480, 180)
    expect(geometry.dots).toHaveLength(1)
    expect(geometry.dots[0].x).toBeCloseTo(240)
    expect(geometry.dots[0].y).toBeCloseTo(22)
    expect(geometry.path).toBe('')
  })

  it('多点等距分布首尾贴边距，路径为折线', () => {
    const series = buildSeries(
      [
        run('c', 'exam', 100, '2026-11-08T10:00:00Z'),
        run('b', 'exam', 50, '2026-11-07T10:00:00Z'),
        run('a', 'exam', 0, '2026-11-06T10:00:00Z'),
      ],
      'exam',
    )
    const geometry = chartGeometry(series, 480, 180)
    expect(geometry.dots.map((dot) => dot.x)).toEqual([32, 240, 448])
    // 输入是时间倒序（c 最新），反序后从左到右是 a(0) → b(50) → c(100)
    expect(geometry.dots.map((dot) => dot.y)).toEqual([158, 90, 22])
    expect(geometry.path.startsWith('M ')).toBe(true)
    expect(geometry.path).toContain(' L ')
    expect(geometry.yTicks.map((tick) => tick.label)).toEqual(['100', '50', '0'])
  })

  it('越界分数按 0–max 夹取，NaN 不产生坐标', () => {
    const series = buildSeries(
      [run('a', 'interview', 12, '2026-11-08T10:00:00Z')],
      'interview',
    )
    const geometry = chartGeometry(series, 480, 180)
    expect(geometry.dots[0].y).toBeCloseTo(22)
  })
})

describe('scoreText 数值口径', () => {
  it('整数不带小数，非整数保留一位', () => {
    expect(scoreText(8)).toBe('8')
    expect(scoreText(6.25)).toBe('6.3')
    expect(scoreText(70)).toBe('70')
  })
})
