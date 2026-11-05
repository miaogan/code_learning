import { describe, expect, it } from 'vitest'
import type { Course, Report, RoleFit, RoleFitItem, Shortfall } from '../api/types'
import {
  GUIDANCE_EMPTY_NOTICE,
  GUIDANCE_MET_NOTICE,
  buildGuidance,
} from '../lib/guidance'

function course(overrides: Partial<Course> = {}): Course {
  return {
    id: 'c1',
    title: '前端基础课',
    direction: '前端',
    level: '入门',
    url: '/courses/c1',
    why: '补齐基础',
    ...overrides,
  }
}

function shortfall(overrides: Partial<Shortfall> = {}): Shortfall {
  return {
    name: '前端基础不牢',
    severity: 'high',
    evidence: 'Q3 · 4/10',
    diagnosis: '基础概念混淆',
    actions: ['先过一遍事件循环'],
    courses: [course()],
    question_ref: 'q3',
    ...overrides,
  }
}

function roleItem(overrides: Partial<RoleFitItem> = {}): RoleFitItem {
  return {
    name: 'JavaScript',
    required: 3,
    user_level: 1,
    gap: 2,
    must: true,
    ...overrides,
  }
}

function roleFit(overrides: Partial<RoleFit> = {}): RoleFit {
  return {
    target_role: '前端工程师',
    role_source: 'profile',
    role_source_label: '简历画像',
    model: { level: '中级', label: '前端工程师 · 中级', direction: '前端' },
    items: [roleItem()],
    missing_must: ['JavaScript'],
    first_fix: ['JavaScript'],
    conclusion: '先补 JavaScript',
    notice: null,
    ...overrides,
  }
}

function report(overrides: Partial<Report> = {}): Report {
  return {
    id: 'r1',
    run_ids: ['run-1'],
    interview_avg: null,
    exam_total: 60,
    shortfalls: [],
    generated_at: '2026-11-04T10:00:00',
    interview_settings: null,
    weakness_map: [],
    resume_pointers: null,
    resume_pointers_notice: null,
    role_fit: null,
    ...overrides,
  }
}

function queryOf(href: string): URLSearchParams {
  const index = href.indexOf('?')
  return new URLSearchParams(index === -1 ? '' : href.slice(index))
}

describe('buildGuidance（推荐学习方向）', () => {
  it('旧报告（role_fit=null）不推荐方向', () => {
    expect(buildGuidance(report())).toEqual([])
  })

  it('主攻方向来自目标岗位模型，先补技能严格保持 first_fix 顺序', () => {
    const input = report({
      role_fit: roleFit({
        items: [
          roleItem({ name: 'JavaScript', gap: 2, must: true }),
          roleItem({ name: '构建与工程化', gap: 1, must: false }),
          roleItem({ name: '浏览器与网络', gap: 0, must: true }),
        ],
        first_fix: ['构建与工程化', 'JavaScript'],
      }),
      shortfalls: [
        shortfall({
          name: '前端基础',
          courses: [
            course({ id: 'fe-1', direction: '前端' }),
            course({ id: 'be-1', direction: '后端' }),
          ],
        }),
      ],
    })

    const guidance = buildGuidance(input)
    // 同一条短板里还挂了一门后端课程，因此除主攻方向外还有一个延伸方向。
    expect(guidance.map((item) => item.direction)).toEqual(['前端', '后端'])
    const primary = guidance[0]
    expect(primary.kind).toBe('primary')
    expect(primary.direction).toBe('前端')
    expect(primary.skills.map((skill) => skill.name)).toEqual(['构建与工程化', 'JavaScript'])
    expect(primary.skills[0]).toMatchObject({ gap: 1, required: 3, must: false })
    // 只收同方向课程，后端方向的课程留给延伸方向。
    expect(primary.courses.map((item) => item.id)).toEqual(['fe-1'])
    expect(queryOf(primary.practiceLink).get('direction')).toBe('前端')
    expect(primary.notice).toBeNull()
  })

  it('主攻方向能力已达标时保留方向卡但给出达标提示', () => {
    const input = report({
      role_fit: roleFit({
        items: [roleItem({ gap: 0 })],
        first_fix: [],
      }),
      shortfalls: [shortfall()],
    })

    const primary = buildGuidance(input)[0]
    expect(primary.direction).toBe('前端')
    expect(primary.skills).toEqual([])
    expect(primary.notice).toBe(GUIDANCE_MET_NOTICE)
  })

  it('延伸方向来自短板课程的真实 direction：去重、按课程数降序、最多 2 个', () => {
    const input = report({
      role_fit: roleFit(),
      shortfalls: [
        shortfall({
          name: '前端基础',
          courses: [course({ id: 'fe-1', direction: '前端' })],
        }),
        shortfall({
          name: '后端并发',
          courses: [
            course({ id: 'be-1', direction: '后端' }),
            course({ id: 'be-2', direction: '后端' }),
          ],
        }),
        shortfall({
          name: '算法不熟',
          courses: [course({ id: 'algo-1', direction: '算法与数据结构' })],
        }),
        shortfall({
          name: 'AI 工程',
          courses: [course({ id: 'ai-1', direction: 'AI 工程' })],
        }),
      ],
    })

    const guidance = buildGuidance(input)
    expect(guidance.map((item) => item.direction)).toEqual([
      '前端',
      '后端',
      '算法与数据结构',
    ])
    expect(guidance[1].kind).toBe('extra')
    expect(guidance[1].courses.map((item) => item.id)).toEqual(['be-1', 'be-2'])
    expect(guidance[1].summary).toContain('后端并发')
    expect(guidance[1].skills).toEqual([])
  })

  it('同一门课挂在多条短板上只出现一次', () => {
    const shared = course({ id: 'shared', direction: '后端' })
    const input = report({
      role_fit: roleFit(),
      shortfalls: [
        shortfall({ name: '短板一', courses: [shared] }),
        shortfall({ name: '短板二', courses: [shared] }),
      ],
    })

    const extra = buildGuidance(input)[1]
    expect(extra.courses.map((item) => item.id)).toEqual(['shared'])
  })

  it('没有方向模型时不假造主攻方向，只给课程方向', () => {
    const input = report({
      role_fit: roleFit({ model: null, first_fix: [] }),
      shortfalls: [shortfall({ courses: [course({ direction: '后端' })] })],
    })

    const guidance = buildGuidance(input)
    expect(guidance).toHaveLength(1)
    expect(guidance[0].kind).toBe('extra')
    expect(guidance[0].direction).toBe('后端')
  })

  it('既没有方向模型也没有带方向的课程时返回空列表', () => {
    const input = report({ role_fit: roleFit({ model: null }), shortfalls: [] })
    expect(buildGuidance(input)).toEqual([])
    expect(GUIDANCE_EMPTY_NOTICE).not.toBe('')
  })
})
