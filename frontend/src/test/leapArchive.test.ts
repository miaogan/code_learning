import { describe, expect, it } from 'vitest'
import type {
  LeapArchive,
  LeapEngineeringItem,
  LeapExpressionItem,
  LeapExpressionStructure,
} from '../api/types'
import {
  STRUCTURE_PARTS,
  expressionSummary,
  gapCompareText,
  isLeapEmpty,
  orderedProjects,
  scaleRows,
  structureParts,
} from '../lib/leapArchive'

function project(overrides: Partial<LeapEngineeringItem> = {}): LeapEngineeringItem {
  return {
    name: '订单系统',
    role: '后端',
    period: '2025',
    bullets: ['拆分库存服务'],
    evidence_count: 1,
    status: 'active',
    ...overrides,
  }
}

function structure(overrides: Partial<LeapExpressionStructure> = {}): LeapExpressionStructure {
  return {
    has_problem: true,
    has_solution: true,
    has_metric: false,
    has_pitfall: false,
    hit_count: 2,
    hint: '仅为关键词自检，不构成评分。',
    ...overrides,
  }
}

function expression(overrides: Partial<LeapExpressionItem> = {}): LeapExpressionItem {
  return {
    run_id: 'run-1',
    question_id: 'iq-1',
    prompt: '讲一个项目',
    answer: '遇到重复扣款问题，采用 Redis 锁解决',
    score: 8,
    comment: '清楚',
    structure: structure(),
    focus_gaps: [],
    gap_hits: [],
    gap_misses: [],
    ...overrides,
  }
}

function archive(overrides: Partial<LeapArchive> = {}): LeapArchive {
  return {
    role_gap: { role_fit: null, notice: '还没有报告' },
    engineering: {
      projects: [],
      data_scale: {},
      tables: 0,
      rag: null,
      radar_techs_seen: 0,
      radar_finished_at: '',
      notice: null,
    },
    expression: { items: [], notice: null },
    generated_at: '2026-11-16T00:00:00+00:00',
    ...overrides,
  }
}

describe('scaleRows', () => {
  it('只列后端给了的 key，不补 0、不改数字', () => {
    const rows = scaleRows({ questions: 1334, attempts: 0, unknown_key: 7 })
    expect(rows.map((row) => row.key)).toEqual(['questions', 'attempts', 'unknown_key'])
    expect(rows[0]).toEqual({ key: 'questions', label: '题库', count: 1334 })
    expect(rows[1].count).toBe(0) // 后端明确给了 0，如实展示
    expect(rows[2].label).toBe('unknown_key') // 未知 key 回落原名
  })
})

describe('orderedProjects', () => {
  it('active 在前、historical 在后，同状态按证据条数降序', () => {
    const rows = orderedProjects([
      project({ name: '历史项目', status: 'historical', evidence_count: 9 }),
      project({ name: '少证据', evidence_count: 1 }),
      project({ name: '多证据', evidence_count: 4 }),
    ])
    expect(rows.map((row) => row.name)).toEqual(['多证据', '少证据', '历史项目'])
  })

  it('不改原数组顺序', () => {
    const original = [project({ name: 'A' }), project({ name: 'B', evidence_count: 3 })]
    orderedProjects(original)
    expect(original.map((row) => row.name)).toEqual(['A', 'B'])
  })
})

describe('structureParts', () => {
  it('命中和缺失分开，顺序固定', () => {
    const result = structureParts(structure())
    expect(result.hits).toEqual(['问题 / 背景', '方案 / 做法'])
    expect(result.misses).toEqual(['指标 / 数据', '踩坑 / 反思'])
    expect(STRUCTURE_PARTS).toHaveLength(4)
  })

  it('全命中时缺失为空', () => {
    const result = structureParts(
      structure({ has_metric: true, has_pitfall: true, hit_count: 4 })
    )
    expect(result.hits).toHaveLength(4)
    expect(result.misses).toEqual([])
  })
})

describe('expressionSummary', () => {
  it('空态与有数据时都明说自检不是评分', () => {
    expect(expressionSummary([])).toBe('还没有已作答的面试发言')
    const text = expressionSummary([
      expression(),
      expression({ score: null, structure: structure({ hit_count: 4 }) }),
    ])
    expect(text).toContain('2 条作答')
    expect(text).toContain('1 条有评分')
    expect(text).toContain('自检不是评分')
  })
})

describe('isLeapEmpty', () => {
  it('三块皆空才为空', () => {
    expect(isLeapEmpty(archive())).toBe(true)
    expect(isLeapEmpty(archive({ engineering: { ...archive().engineering, projects: [project()] } }))).toBe(false)
  })
})

describe('gapCompareText（r111 JD 缺口对照）', () => {
  it('没有缺口词的场次返回 null，不渲染对照行', () => {
    expect(gapCompareText(expression())).toBeNull()
  })

  it('命中 / 未提到沿用服务端结果，并明说不是掌握度结论', () => {
    const text = gapCompareText(
      expression({ focus_gaps: ['Redis 缓存', 'RAG 检索增强'], gap_hits: ['RAG 检索增强'], gap_misses: ['Redis 缓存'] }),
    )
    expect(text).toContain('RAG 检索增强')
    expect(text).toContain('Redis 缓存')
    expect(text).toContain('不是掌握度结论')
  })

  it('全部未提到时两边都如实展示，不补造命中', () => {
    const text = gapCompareText(
      expression({ focus_gaps: ['Docker 与容器编排'], gap_hits: [], gap_misses: ['Docker 与容器编排'] }),
    )
    expect(text).toContain('提到 无')
    expect(text).toContain('Docker 与容器编排')
  })
})
