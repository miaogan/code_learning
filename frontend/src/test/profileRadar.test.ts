import { describe, expect, it } from 'vitest'
import type { Report, RoleFit, RunSummary, WeaknessItem } from '../api/types'
import {
  CAPABILITY_BASELINE,
  CAPABILITY_TITLE,
  capabilityAxes,
  capabilityCoverage,
  radarPath,
  radarPoints,
  radarPolygon,
} from '../lib/profileRadar'
import { DIRECTIONS } from '../lib/questionDirections'

function weak(overrides: Partial<WeaknessItem>): WeaknessItem {
  return {
    key: 'k',
    point: 'p',
    direction: 'AI 工程',
    wrong: 0,
    total: 0,
    rate: 0,
    avg: 0,
    difficulty: [],
    essentiality: [],
    samples: [],
    summary: '',
    ...overrides,
  }
}

function reportWith(items: WeaknessItem[] | null): Report {
  return {
    id: 'r1',
    run_ids: [],
    interview_avg: null,
    exam_total: null,
    shortfalls: [],
    generated_at: '2026-11-10T00:00:00Z',
    interview_settings: null,
    weakness_map: items,
    resume_pointers: null,
    resume_pointers_notice: null,
    role_fit: null,
  }
}

function run(kind: RunSummary['kind'], score: number | null, id = 'x'): RunSummary {
  return {
    id,
    kind,
    score,
    shortfall_count: null,
    created_at: '2026-11-10T00:00:00Z',
    interview_settings: null,
  }
}

function axisOf(input: Parameters<typeof capabilityAxes>[0], key: string) {
  return capabilityAxes(input).find((axis) => axis.key === key)
}

function roleFit(overrides: Partial<RoleFit>): RoleFit {
  return {
    target_role: 'AI 应用工程师',
    role_source: 'profile',
    role_source_label: '简历画像',
    model: null,
    items: [],
    missing_must: [],
    first_fix: [],
    conclusion: null,
    notice: null,
    ...overrides,
  }
}

describe('capabilityAxes 轴定义', () => {
  it('七条轴顺序与标题固定为技术力 / 深度 / 广度 / 基础扎实度 / 稳定度 / 学习力 / 岗位匹配', () => {
    const axes = capabilityAxes({ report: null, runs: [] })
    expect(axes.map((axis) => axis.key)).toEqual([
      'technique',
      'depth',
      'breadth',
      'fundamentals',
      'stability',
      'learning',
      'readiness',
    ])
    expect(axes.map((axis) => axis.title)).toEqual([
      '技术力',
      '深度',
      '广度',
      '基础扎实度',
      '稳定度',
      '学习力',
      '岗位匹配',
    ])
    expect(CAPABILITY_TITLE.readiness).toBe('岗位匹配')
  })

  it('没有任何测评数据：七条轴都是 0 且不算已填，不伪造读数', () => {
    const axes = capabilityAxes({ report: null, runs: [] })
    expect(axes).toHaveLength(7)
    expect(axes.every((axis) => axis.ratio === 0 && !axis.filled)).toBe(true)
    expect(axes.every((axis) => axis.reading === '暂无测评数据')).toBe(true)
    expect(capabilityCoverage(axes)).toBe(0)
  })
})

describe('技术力：最近一次有分的测评', () => {
  it('面试按 /10 归一，未计分记录跳过（不补 0）', () => {
    const axis = axisOf(
      { report: null, runs: [run('exam', null), run('interview', 6.5)] },
      'technique',
    )
    expect(axis?.ratio).toBeCloseTo(0.65)
    expect(axis?.reading).toBe('最近一次面试 6.5/10')
    expect(axis?.filled).toBe(true)
  })

  it('笔试按 /100 归一，整数不带小数', () => {
    const axis = axisOf({ report: null, runs: [run('exam', 72)] }, 'technique')
    expect(axis?.ratio).toBeCloseTo(0.72)
    expect(axis?.reading).toBe('最近一次笔试 72/100')
  })

  it('服务端已倒序：只取第一条有分记录，不自行重排', () => {
    const axis = axisOf(
      { report: null, runs: [run('exam', 80), run('exam', 40)] },
      'technique',
    )
    expect(axis?.ratio).toBeCloseTo(0.8)
  })
})

describe('学习力：同类测评相邻对比', () => {
  it('面试与笔试不互相比较，分别统计提升或持平的比例', () => {
    // 旧 → 新：面试 5 → 6（提升），6 → 6（持平）；笔试 60 → 50（下降）⇒ 2/3
    const axis = axisOf(
      {
        report: null,
        runs: [
          run('exam', 50),
          run('interview', 6),
          run('exam', 60),
          run('interview', 6),
          run('interview', 5),
        ],
      },
      'learning',
    )
    expect(axis?.ratio).toBeCloseTo(2 / 3)
    expect(axis?.reading).toBe('近 3 次同类对比 · 2 次提升或持平')
  })

  it('只有一条记录：无可比对，按无数据（不是 0 分）', () => {
    const axis = axisOf({ report: null, runs: [run('exam', 90)] }, 'learning')
    expect(axis?.filled).toBe(false)
    expect(axis?.reading).toBe('暂无测评数据')
  })

  it('每次都下降：ratio 为 0 但仍是「有证据」', () => {
    const axis = axisOf(
      { report: null, runs: [run('exam', 30), run('exam', 40)] },
      'learning',
    )
    expect(axis?.ratio).toBe(0)
    expect(axis?.filled).toBe(true)
  })
})

describe('深度：挑战难度分组的得分率', () => {
  it('只聚合 difficulty 含 challenge 的组，每组只计一次', () => {
    const axis = axisOf(
      {
        report: reportWith([
          weak({ difficulty: ['challenge'], total: 10, wrong: 4 }),
          weak({ difficulty: ['intermediate', 'challenge'], total: 10, wrong: 2 }),
          weak({ difficulty: ['basic'], total: 30, wrong: 3 }),
        ]),
        runs: [],
      },
      'depth',
    )
    // (20 - 6) / 20 = 70%
    expect(axis?.ratio).toBeCloseTo(0.7)
    expect(axis?.reading).toBe('挑战题得分率 70%（20 题）')
  })

  it('没有挑战题 / 没有报告 ⇒ 无数据', () => {
    expect(axisOf({ report: reportWith([weak({ difficulty: ['basic'] })]), runs: [] }, 'depth')?.filled)
      .toBe(false)
    expect(axisOf({ report: null, runs: [] }, 'depth')?.filled).toBe(false)
    expect(axisOf({ report: reportWith(null), runs: [] }, 'depth')?.filled).toBe(false)
  })
})

describe('广度：测评覆盖的方向数', () => {
  it('去重计数、空方向不占一格、分母为全库方向数', () => {
    const axis = axisOf(
      {
        report: reportWith([
          weak({ direction: 'AI 工程' }),
          weak({ direction: 'AI 工程' }),
          weak({ direction: '后端' }),
          weak({ direction: '' }),
        ]),
        runs: [],
      },
      'breadth',
    )
    expect(axis?.ratio).toBeCloseTo(2 / DIRECTIONS.length)
    expect(axis?.reading).toBe(`覆盖 2/${DIRECTIONS.length} 个方向`)
  })

  it('空薄弱地图 / 旧报告 ⇒ 无数据', () => {
    expect(axisOf({ report: reportWith([]), runs: [] }, 'breadth')?.filled).toBe(false)
    expect(axisOf({ report: reportWith(null), runs: [] }, 'breadth')?.filled).toBe(false)
  })
})

describe('基础扎实度：基础 / 进阶难度分组的得分率', () => {
  it('与深度互补：只聚合 basic / intermediate，挑战题不计入', () => {
    const axis = axisOf(
      {
        report: reportWith([
          weak({ difficulty: ['basic'], total: 30, wrong: 3 }),
          weak({ difficulty: ['intermediate'], total: 20, wrong: 4 }),
          weak({ difficulty: ['challenge'], total: 10, wrong: 10 }),
        ]),
        runs: [],
      },
      'fundamentals',
    )
    // (50 - 7) / 50 = 86%
    expect(axis?.ratio).toBeCloseTo(0.86)
    expect(axis?.reading).toBe('基础 / 进阶题得分率 86%（50 题）')
    expect(axis?.filled).toBe(true)
  })

  it('只有挑战题 / 无难度标签 / 没有报告 ⇒ 无数据', () => {
    const challengeOnly = reportWith([weak({ difficulty: ['challenge'], total: 5 })])
    expect(axisOf({ report: challengeOnly, runs: [] }, 'fundamentals')?.filled).toBe(false)
    expect(
      axisOf({ report: reportWith([weak({ difficulty: [] })]), runs: [] }, 'fundamentals')?.filled,
    ).toBe(false)
    expect(axisOf({ report: null, runs: [] }, 'fundamentals')?.filled).toBe(false)
  })
})

describe('稳定度：同类测评得分波动', () => {
  it('1 − 变异系数：笔试 60/70/80 ⇒ 波动 12%', () => {
    const axis = axisOf(
      { report: null, runs: [run('exam', 80, 'c'), run('exam', 70, 'b'), run('exam', 60, 'a')] },
      'stability',
    )
    // 均值 70、标准差 ≈ 8.165 ⇒ cv ≈ 0.1166
    expect(axis?.ratio).toBeCloseTo(0.8834, 3)
    expect(axis?.reading).toBe('同类 3 次 · 得分波动 12%')
    expect(axis?.filled).toBe(true)
  })

  it('多次完全同分 ⇒ 稳定度为满值（只代表发挥稳定，不代表分数高）', () => {
    const axis = axisOf(
      { report: null, runs: [run('interview', 5), run('interview', 5)] },
      'stability',
    )
    expect(axis?.ratio).toBe(1)
    expect(axis?.reading).toBe('同类 2 次 · 得分波动 0%')
  })

  it('只有一条有分记录 ⇒ 算不出波动，按无数据（不是 0 分）', () => {
    const axis = axisOf({ report: null, runs: [run('exam', 90), run('exam', null)] }, 'stability')
    expect(axis?.filled).toBe(false)
    expect(axis?.reading).toBe('暂无测评数据')
  })
})

describe('岗位匹配：目标岗位技能达标率', () => {
  it('按 user_level / required 均值，required 为 0 的行不计入', () => {
    const report: Report = {
      ...reportWith([]),
      role_fit: roleFit({
        items: [
          { name: 'Python', required: 3, user_level: 2, gap: 1, must: true },
          { name: 'RAG', required: 2, user_level: 2, gap: 0, must: true },
          { name: '可选项', required: 0, user_level: 0, gap: 0, must: false },
        ],
      }),
    }
    const axis = axisOf({ report, runs: [] }, 'readiness')
    // (2/3 + 1) / 2 ≈ 0.8333
    expect(axis?.ratio).toBeCloseTo(0.8333, 3)
    expect(axis?.reading).toBe('AI 应用工程师 · 技能达标 1/2')
    expect(axis?.filled).toBe(true)
  })

  it('无岗位模型 / 空差距表 ⇒ 无数据', () => {
    const empty = { ...reportWith([]), role_fit: roleFit({ items: [] }) }
    expect(axisOf({ report: empty, runs: [] }, 'readiness')?.filled).toBe(false)
    expect(axisOf({ report: reportWith([]), runs: [] }, 'readiness')?.filled).toBe(false)
  })

  it('缺 target_role 时用「目标岗位」占位，不编造岗位名', () => {
    const report: Report = {
      ...reportWith([]),
      role_fit: roleFit({
        target_role: null,
        items: [{ name: 'Python', required: 2, user_level: 1, gap: 1, must: true }],
      }),
    }
    expect(axisOf({ report, runs: [] }, 'readiness')?.reading).toBe('目标岗位 · 技能达标 0/1')
  })
})

describe('参考基线', () => {
  it('两条参考线是固定刻度（产品设定，非真实市场统计）', () => {
    expect(CAPABILITY_BASELINE.average).toBe(0.5)
    expect(CAPABILITY_BASELINE.top).toBe(0.9)
  })
})

describe('radarPoints / radarPath / radarPolygon', () => {
  it('第一条轴在正上方，其余顺时针均分', () => {
    const points = radarPoints([1, 1, 1, 1], 100, 100, 40)
    expect(points[0].x).toBeCloseTo(100)
    expect(points[0].y).toBeCloseTo(60)
    expect(points[1].x).toBeCloseTo(140)
    expect(points[1].y).toBeCloseTo(100)
  })

  it('越界读数按 0/1 夹取，非有限值按 0', () => {
    const points = radarPoints([1.4, -0.2, Number.NaN], 0, 0, 10)
    expect(points[0].x).toBeCloseTo(0)
    expect(points[0].y).toBeCloseTo(-10)
    expect(points[1].x).toBeCloseTo(0)
    expect(points[2].x).toBeCloseTo(0)
    expect(points[2].y).toBeCloseTo(0)
  })

  it('path 与 polygon 都是闭合形状；不足 3 点不画区域', () => {
    const points = radarPoints([1, 1, 1], 0, 0, 10)
    expect(radarPath(points)).toMatch(/^M .* Z$/)
    expect(radarPolygon(points).split(' ')).toHaveLength(3)
    expect(radarPath(radarPoints([1, 1], 0, 0, 10))).toBe('')
  })
})
