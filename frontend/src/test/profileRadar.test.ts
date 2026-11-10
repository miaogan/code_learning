import { describe, expect, it } from 'vitest'
import type { Profile } from '../api/types'
import {
  RADAR_REFERENCE,
  radarAxes,
  radarCoverage,
  radarPath,
  radarPoints,
} from '../lib/profileRadar'

/** 最小画像：只关心雷达读的 5 个维度，其余字段留空值。 */
function makeProfile(overrides: Partial<Profile> = {}): Profile {
  return {
    id: 'p1',
    resume_id: 'r1',
    updated_at: '2026-11-10T00:00:00Z',
    skills: [],
    tech_stack: [],
    years_experience: null,
    projects: [],
    target_role: null,
    ...overrides,
  }
}

function skill(name: string, status?: 'active' | 'historical') {
  return { name, source_quote: `${name} 证据`, status }
}

describe('radarAxes 填充度口径', () => {
  it('空画像：5 维全 0，年限与岗位显示未填写', () => {
    const axes = radarAxes(makeProfile())
    expect(axes).toHaveLength(5)
    expect(axes.every((axis) => axis.ratio === 0)).toBe(true)
    expect(radarCoverage(axes)).toBe(0)
    expect(axes[2].reading).toBe('未填写')
    expect(axes[4].reading).toBe('未填写')
    expect(axes[0].reading).toBe('0 个技能')
  })

  it('历史条目不计入（与主卡片、confirmedDimensions 同一口径）', () => {
    const axes = radarAxes(
      makeProfile({ skills: [skill('Python'), skill('旧技能', 'historical')] }),
    )
    expect(axes[0].reading).toBe('1 个技能')
    expect(axes[0].ratio).toBeCloseTo(1 / RADAR_REFERENCE.skills)
  })

  it('超过参考上限按满轴夹取，但读数仍是真实计数', () => {
    const many = Array.from({ length: 12 }, (_unused, index) => skill(`S${index}`))
    const axes = radarAxes(makeProfile({ skills: many }))
    expect(axes[0].ratio).toBe(1)
    expect(axes[0].reading).toBe('12 个技能')
  })

  it('年限按 5 年满轴；0 年是已填写但比例为 0', () => {
    const five = radarAxes(makeProfile({ years_experience: 5 }))[2]
    expect(five.ratio).toBe(1)
    expect(five.filled).toBe(true)

    const two = radarAxes(makeProfile({ years_experience: 2 }))[2]
    expect(two.ratio).toBeCloseTo(0.4)
    expect(two.reading).toBe('2 年')

    const fresh = radarAxes(makeProfile({ years_experience: 0 }))[2]
    expect(fresh.ratio).toBe(0)
    expect(fresh.filled).toBe(true)
    expect(fresh.reading).toBe('0 年')
  })

  it('目标岗位只认非空白字符串', () => {
    expect(radarAxes(makeProfile({ target_role: '   ' }))[4].filled).toBe(false)
    const filled = radarAxes(makeProfile({ target_role: 'AI 应用工程师' }))[4]
    expect(filled.ratio).toBe(1)
    expect(filled.reading).toBe('AI 应用工程师')
  })

  it('项目按 3 段满轴，覆盖数统计已填写维度', () => {
    const axes = radarAxes(
      makeProfile({
        projects: [
          { name: 'A', role: null, period: null, bullets: [], source_quote: 'A 证据' },
        ],
        target_role: 'Agent 后端',
      }),
    )
    expect(axes[3].ratio).toBeCloseTo(1 / RADAR_REFERENCE.projects)
    expect(radarCoverage(axes)).toBe(2)
  })
})

describe('radarPoints / radarPath 投影', () => {
  it('第一条轴在正上方，按半径投影', () => {
    const points = radarPoints([1, 1, 1, 1, 1], 100, 100, 40)
    expect(points[0].x).toBeCloseTo(100)
    expect(points[0].y).toBeCloseTo(60)
    expect(points).toHaveLength(5)
  })

  it('越界与非法值按 0 / 1 夹取（不抛错）', () => {
    const points = radarPoints([1.4, -0.2, Number.NaN], 0, 0, 10)
    const radii = points.map((point) => Math.hypot(point.x, point.y))
    expect(radii[0]).toBeCloseTo(10)
    expect(radii[1]).toBeCloseTo(0)
    expect(radii[2]).toBeCloseTo(0)
  })

  it('不足 3 个顶点不生成闭合路径', () => {
    expect(radarPath(radarPoints([1, 1], 0, 0, 10))).toBe('')
    expect(radarPath(radarPoints([1, 1, 1], 0, 0, 10))).toMatch(/^M .+ Z$/)
  })
})
