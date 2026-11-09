import { describe, expect, it } from 'vitest'
import type { Report, WeaknessItem } from '../api/types'
import { ALL_TUTORIAL_CHAPTERS } from '../lib/tutorials'
import { buildStudyPlan } from '../lib/studyPlan'

function makeReport(weakness: WeaknessItem[] | null): Report {
  return {
    id: 'report-r51',
    run_ids: [],
    interview_avg: null,
    exam_total: null,
    shortfalls: [],
    generated_at: '2026-11-09T00:00:00Z',
    interview_settings: null,
    weakness_map: weakness,
    resume_pointers: null,
    resume_pointers_notice: null,
    role_fit: null,
  }
}

function weakness(overrides: Partial<WeaknessItem> = {}): WeaknessItem {
  return {
    key: '多 Agent 编排|challenge|must_know',
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

function tasksOf(report: Report, citations?: boolean) {
  return buildStudyPlan(report, { dailyMinutes: 30, citations })
    .days.flatMap((day) => day.tasks)
}

describe('r51 学习计划的检索引用', () => {
  it('默认不开启检索时任务零 citations 字段（与 r50 行为等价）', () => {
    const tasks = tasksOf(makeReport([weakness()]))
    expect(tasks.length).toBeGreaterThan(0)
    expect(tasks.every((task) => task.citations === undefined)).toBe(true)
  })

  it('开启后教程任务带依据，且每个引用都指向真实小节锚点', () => {
    const tasks = tasksOf(makeReport([weakness()]), true)
    const withCitations = tasks.filter((task) => task.citations !== undefined)
    expect(withCitations.length).toBeGreaterThan(0)
    for (const task of withCitations) {
      expect(task.citations?.length).toBeGreaterThan(0)
      for (const citation of task.citations ?? []) {
        expect(citation.href).toBe(`/learn/${citation.chapter_id}#tutorial-${citation.section_id}`)
        const chapter = ALL_TUTORIAL_CHAPTERS.find((item) => item.id === citation.chapter_id)
        expect(chapter).toBeDefined()
        expect(chapter?.sections.some((section) => section.id === citation.section_id)).toBe(true)
        expect(Number.isFinite(citation.score)).toBe(true)
      }
    }
  })

  it('相同入参两次构建的引用完全一致（确定性可复算）', () => {
    const report = makeReport([weakness()])
    expect(tasksOf(report, true)).toEqual(tasksOf(report, true))
  })

  it('旧报告返回空计划，不编造任务与引用', () => {
    const plan = buildStudyPlan(makeReport(null), { dailyMinutes: 30, citations: true })
    expect(plan.days).toEqual([])
    expect(plan.days.flatMap((day) => day.tasks)).toEqual([])
  })

  it('检索无命中时静默回落，计划仍可生成', () => {
    const tasks = tasksOf(makeReport([weakness({ point: '不存在的短板词', summary: 'zzzz' })]), true)
    expect(tasks.length).toBeGreaterThan(0)
    expect(tasks.every((task) => task.href.startsWith('/'))).toBe(true)
  })
})
