import { describe, expect, it } from 'vitest'
import type { Course, Report, Shortfall, WeaknessItem } from '../api/types'
import {
  PLAN_DAY_COUNT,
  buildWeekPlan,
  parsePlanProgress,
  practiceHref,
  weekPlanStorageKey,
} from '../lib/reportPlan'

function weakness(overrides: Partial<WeaknessItem> = {}): WeaknessItem {
  return {
    key: '前端|basic,|must_know,',
    point: '前端 · 基础 · 必须掌握',
    direction: '前端',
    wrong: 2,
    total: 3,
    rate: 0.667,
    avg: 4.5,
    difficulty: ['basic'],
    essentiality: ['must_know'],
    samples: [],
    summary: '前端基础题错得多',
    ...overrides,
  }
}

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

function report(overrides: Partial<Report> = {}): Report {
  return {
    id: 'r1',
    run_ids: ['run-1'],
    interview_avg: null,
    exam_total: 60,
    shortfalls: [],
    generated_at: '2026-11-04T10:00:00',
    interview_settings: null,
    weakness_map: [weakness()],
    resume_pointers: null,
    resume_pointers_notice: null,
    role_fit: null,
    ...overrides,
  }
}

/** 解析站内链接的 query，避免手写 URL 编码差异。 */
function queryOf(href: string): URLSearchParams {
  const index = href.indexOf('?')
  return new URLSearchParams(index === -1 ? '' : href.slice(index))
}

describe('practiceHref（计划任务链接）', () => {
  it('全默认时给不带参数的 /practice', () => {
    expect(practiceHref({})).toBe('/practice')
    expect(practiceHref({ direction: 'all', difficulty: 'all', limit: 10 })).toBe(
      '/practice?limit=10',
    )
  })

  it('只写真实生效的筛选，空值不落 query', () => {
    expect(practiceHref({ scope: 'wrong', limit: 0 })).toBe('/practice?scope=wrong&limit=0')
    expect(practiceHref({ direction: '前端', difficulty: 'basic' })).toBe(
      `/practice?direction=${encodeURIComponent('前端')}&difficulty=basic`,
    )
  })
})

describe('buildWeekPlan（7 天补短板计划）', () => {
  it('旧报告（weakness_map=null）与无计分题（[]）都不排计划', () => {
    expect(buildWeekPlan(report({ weakness_map: null }))).toEqual([])
    expect(buildWeekPlan(report({ weakness_map: [] }))).toEqual([])
  })

  it('固定 7 天，编号连续，第 1 天按最靠前的薄弱分组出专项练习', () => {
    const plan = buildWeekPlan(report())
    expect(plan).toHaveLength(PLAN_DAY_COUNT)
    expect(plan.map((day) => day.day)).toEqual([1, 2, 3, 4, 5, 6, 7])

    const first = plan[0]
    expect(first.title).toBe('补短板 · 前端 · 基础 · 必须掌握')
    expect(first.focus).toBe('前端基础题错得多')
    const practice = first.tasks.find((task) => task.kind === 'practice')
    expect(practice).toBeDefined()
    const query = queryOf(practice?.href ?? '')
    expect(query.get('direction')).toBe('前端')
    expect(query.get('difficulty')).toBe('basic')
    expect(query.get('essentiality')).toBe('must_know')
    expect(query.get('limit')).toBe('10')
  })

  it('同方向课程优先推荐；没有同方向课程时退到报告里的第一门（不造课）', () => {
    const withMatch = buildWeekPlan(
      report({
        shortfalls: [
          shortfall({ courses: [course({ id: 'c1' }), course({ id: 'c2', direction: '后端' })] }),
        ],
      }),
    )
    const matchedCourses = withMatch[0].tasks.filter((task) => task.kind === 'course')
    expect(matchedCourses.map((task) => task.label)).toEqual(['前端基础课'])

    const noMatch = buildWeekPlan(
      report({ shortfalls: [shortfall({ courses: [course({ id: 'c9', direction: '后端' })] })] }),
    )
    expect(noMatch[0].tasks.filter((task) => task.kind === 'course').map((task) => task.label)).toEqual(
      ['前端基础课'],
    )
  })

  it('同一门课挂在多条短板上只推荐一次（按课程 id 去重）', () => {
    const plan = buildWeekPlan(
      report({
        shortfalls: [shortfall(), shortfall({ name: '前端工程化弱', courses: [course()] })],
      }),
    )
    const courseTasks = plan[0].tasks.filter((task) => task.kind === 'course')
    expect(courseTasks).toHaveLength(1)
  })

  it('薄弱分组不足 3 个时用综合练习补齐第 2、3 天，天数仍为 7', () => {
    const plan = buildWeekPlan(report())
    expect(plan[1].title).toBe('综合练习')
    expect(plan[1].tasks[0].label).toBe('综合练习 10 题')
    expect(plan[2].title).toBe('综合练习')
    expect(plan[2].tasks[0].label).toBe('综合练习 20 题')
    expect(plan).toHaveLength(PLAN_DAY_COUNT)
  })

  it('后 4 天固定为错题清零 → 综合 → 模拟笔试 → 模拟面试 + 复盘', () => {
    const plan = buildWeekPlan(report())
    expect(plan[3].title).toBe('错题清零')
    expect(queryOf(plan[3].tasks[0].href ?? '').get('scope')).toBe('wrong')
    expect(queryOf(plan[3].tasks[0].href ?? '').get('limit')).toBe('0')
    expect(plan[4].tasks[0].href).toBe('/practice?limit=20')
    expect(plan[5].tasks[0].href).toBe('/exam')
    expect(plan[6].tasks.map((task) => task.href)).toEqual(['/interview', '/report'])
  })

  it('多个薄弱分组时前 3 天各取一个分组', () => {
    const plan = buildWeekPlan(
      report({
        weakness_map: [
          weakness({ key: 'k1', point: '前端 · 基础' }),
          weakness({ key: 'k2', point: '后端 · 进阶', direction: '后端', difficulty: ['intermediate'] }),
          weakness({ key: 'k3', point: '算法 · 挑战', direction: '算法与数据结构', difficulty: ['challenge'] }),
        ],
      }),
    )
    expect(plan[0].title).toBe('补短板 · 前端 · 基础')
    expect(plan[1].title).toBe('补短板 · 后端 · 进阶')
    expect(plan[2].title).toBe('补短板 · 算法 · 挑战')
  })
})

describe('打卡进度（本地存储）', () => {
  it('存储键按账号 + 报告隔离', () => {
    expect(weekPlanStorageKey('u1', 'r1')).toBe('weekplan:u1:r1')
  })

  it('解析合法记录：去重、升序；非法 JSON / 非数组 / 越界值一律丢弃', () => {
    expect(parsePlanProgress('[3,1,3]')).toEqual([1, 3])
    expect(parsePlanProgress('[0,8,2.5,"3"]')).toEqual([])
    expect(parsePlanProgress('null')).toEqual([])
    expect(parsePlanProgress('oops')).toEqual([])
    expect(parsePlanProgress(null)).toEqual([])
  })
})
