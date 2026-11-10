import { describe, expect, it } from 'vitest'
import type { Report, RoleFit, WeaknessItem } from '../api/types'
import {
  COACH_DETAIL_MAX,
  COACH_DIRECTION_LIMIT,
  COACH_FOCUS_MAX,
  COACH_GOAL_MAX,
  COACH_MATERIAL_LIMIT,
  buildCoachMaterials,
  clampText,
  coachFocusOf,
  coachGoalOf,
  weakDirectionsOf,
} from '../lib/coachMaterials'
import { chapterById } from '../lib/tutorials'

function makeReport(weakness: WeaknessItem[] | null, roleFit: RoleFit | null = null): Report {
  return {
    id: 'report-r65',
    run_ids: [],
    interview_avg: null,
    exam_total: null,
    shortfalls: [],
    generated_at: '2026-11-10T00:00:00Z',
    interview_settings: null,
    weakness_map: weakness,
    resume_pointers: null,
    resume_pointers_notice: null,
    role_fit: roleFit,
  }
}

function weakness(overrides: Partial<WeaknessItem> = {}): WeaknessItem {
  return {
    key: 'AI 工程|challenge|must_know',
    point: '多 Agent 编排',
    direction: 'AI 工程',
    sub_direction: 'Agent',
    difficulty: ['challenge'],
    essentiality: ['must_know'],
    wrong: 3,
    total: 4,
    rate: 0.75,
    avg: 4,
    samples: [],
    summary: '循环转派与全局预算，缺少终止判据',
    ...overrides,
  } as WeaknessItem
}

function roleFit(overrides: Partial<RoleFit> = {}): RoleFit {
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

describe('r65 学习教练：薄弱方向挑选', () => {
  it('按错误率降序、按方向去重，最多取 COACH_DIRECTION_LIMIT 个方向', () => {
    const picked = weakDirectionsOf(
      makeReport([
        weakness({ key: 'a', direction: '前端', rate: 0.2 }),
        weakness({ key: 'b', direction: 'AI 工程', rate: 0.8, wrong: 2 }),
        weakness({ key: 'c', direction: 'AI 工程', rate: 0.9, wrong: 5 }),
        weakness({ key: 'd', direction: '后端', rate: 0.5 }),
        weakness({ key: 'e', direction: 'SQL 与数据库', rate: 0.1 }),
      ]),
    )
    expect(picked.map((item) => item.direction)).toEqual(['AI 工程', '后端', '前端'])
    // 同方向保留错误率更高的那一条（0.9 的 c），不是报告里的原序
    expect(picked[0].key).toBe('c')
    expect(picked.length).toBeLessThanOrEqual(COACH_DIRECTION_LIMIT)
  })

  it('错误率相同按错题数降序，再按方向名排序', () => {
    const picked = weakDirectionsOf(
      makeReport([
        weakness({ key: 'x', direction: '后端', rate: 0.6, wrong: 1 }),
        weakness({ key: 'y', direction: '前端', rate: 0.6, wrong: 1 }),
        weakness({ key: 'z', direction: '中间件与运维', rate: 0.6, wrong: 4 }),
      ]),
    )
    expect(picked.map((item) => item.direction)).toEqual(['中间件与运维', '后端', '前端'])
  })

  it('过滤无题组与空方向，旧报告 null 返回空数组', () => {
    expect(weakDirectionsOf(makeReport(null))).toEqual([])
    expect(
      weakDirectionsOf(
        makeReport([
          weakness({ key: 'zero', direction: '前端', total: 0, rate: 0 }),
          weakness({ key: 'nodir', direction: '', total: 4, rate: 1 }),
        ]),
      ),
    ).toEqual([])
  })
})

describe('r65 学习教练：文本夹取', () => {
  it('clampText 压平换行与连续空白并 trim', () => {
    expect(clampText('  第一行\n第二行   第三段  ', 100)).toBe('第一行 第二行 第三段')
  })

  it('clampText 超长截断补省略号，limit<=0 返回空串', () => {
    expect(clampText('一二三四五', 4)).toBe('一二三四…')
    expect(clampText('一二三四五', 5)).toBe('一二三四五')
    expect(clampText('一二三', 0)).toBe('')
  })
})

describe('r65 学习教练：材料组装', () => {
  it('每个材料都指向真实教程小节，方向 / 二级方向 / 难度与章节一致', () => {
    const materials = buildCoachMaterials(makeReport([weakness()]))
    expect(materials.length).toBeGreaterThan(0)
    for (const material of materials) {
      expect(material.href.startsWith('/learn/')).toBe(true)
      expect(material.href).toContain('#tutorial-')
      const chapter = chapterById(material.href.split('#')[0].replace('/learn/', ''))
      expect(chapter).toBeDefined()
      expect(material.direction).toBe(chapter?.direction)
      expect(material.sub_direction).toBe(chapter?.sub_direction)
      expect(material.level).toBe(chapter?.level)
      expect(material.title.length).toBeGreaterThan(0)
      // 摘要压平后不得超过上限（超长时补一个省略号）
      const detail = material.detail ?? ''
      expect(detail.length).toBeLessThanOrEqual(COACH_DETAIL_MAX + 1)
      expect(detail.includes('\n')).toBe(false)
    }
  })

  it('二级方向零命中时静默回落到方向级，不丢整个方向', () => {
    // 计算机基础下有「组成原理」这一合法子方向，但站内暂无该子方向章节
    const materials = buildCoachMaterials(
      makeReport([weakness({ direction: '计算机基础', sub_direction: '组成原理', rate: 0.9 })]),
    )
    expect(materials.length).toBeGreaterThan(0)
    expect(materials.every((material) => material.direction === '计算机基础')).toBe(true)
  })

  it('三个方向合计不超过 COACH_MATERIAL_LIMIT 且 href 不重复', () => {
    const materials = buildCoachMaterials(
      makeReport([
        weakness({ key: 'a', direction: 'AI 工程', sub_direction: 'Agent', rate: 0.9 }),
        weakness({ key: 'b', direction: '后端', sub_direction: '通用后端', rate: 0.7 }),
        weakness({ key: 'c', direction: 'SQL 与数据库', sub_direction: '索引', rate: 0.5 }),
      ]),
    )
    expect(materials.length).toBeLessThanOrEqual(COACH_MATERIAL_LIMIT)
    const hrefs = materials.map((material) => material.href)
    expect(new Set(hrefs).size).toBe(hrefs.length)
  })

  it('无计分短板时返回空材料，不编造上下文', () => {
    expect(buildCoachMaterials(makeReport([]))).toEqual([])
    expect(buildCoachMaterials(makeReport(null))).toEqual([])
  })
})

describe('r65 学习教练：提示词字段', () => {
  it('coachFocusOf 取目标岗位并夹到上限，缺目标岗位给空串', () => {
    expect(coachFocusOf(makeReport([], roleFit()))).toBe('AI 应用工程师')
    expect(coachFocusOf(makeReport([], null))).toBe('')
    const long = coachFocusOf(makeReport([], roleFit({ target_role: '高级'.repeat(30) })))
    expect(long.length).toBeLessThanOrEqual(COACH_FOCUS_MAX + 1)
    expect(long.endsWith('…')).toBe(true)
  })

  it('coachGoalOf 用最薄弱方向写默认目标，含二级方向与错误率', () => {
    expect(coachGoalOf(makeReport([weakness()]))).toBe(
      '优先补强 AI 工程 · Agent（该分组错误率 75%，共 4 题）',
    )
    expect(
      coachGoalOf(makeReport([weakness({ direction: '后端', sub_direction: '', rate: 0.5 })])),
    ).toBe('优先补强 后端（该分组错误率 50%，共 4 题）')
    expect(coachGoalOf(makeReport([]))).toBe('')
  })

  it('coachGoalOf 超长目标夹到 GOAL_MAX 且保留省略号', () => {
    const goal = coachGoalOf(
      makeReport([weakness({ direction: '超长方向'.repeat(50), sub_direction: '', rate: 1 })]),
    )
    expect(goal.length).toBeLessThanOrEqual(COACH_GOAL_MAX + 1)
    expect(goal.endsWith('…')).toBe(true)
  })
})
