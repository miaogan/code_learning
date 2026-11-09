import { describe, expect, it } from 'vitest'
import type { Report, WeaknessItem } from '../api/types'
import { ALL_TUTORIAL_CHAPTERS } from '../lib/tutorials'
import type { LearnProgressState } from '../lib/learnProgress'
import {
  PLAN_DAY_COUNT,
  buildStudyPlan,
  practiceHref,
  parsePlanState,
  parseStoredPlan,
  planStats,
  type PlanMinutes,
} from '../lib/studyPlan'

function makeReport(weakness: WeaknessItem[] | null): Report {
  return {
    id: 'report-1',
    run_ids: [],
    interview_avg: null,
    exam_total: null,
    shortfalls: [],
    generated_at: '2026-11-08T00:00:00Z',
    interview_settings: null,
    weakness_map: weakness,
    resume_pointers: null,
    resume_pointers_notice: null,
    role_fit: null,
  }
}

function weakness(
  point: string,
  direction: string,
  overrides: Partial<WeaknessItem> = {},
): WeaknessItem {
  return {
    key: point,
    point,
    direction,
    difficulty: ['basic'],
    essentiality: ['must_know'],
    wrong: 2,
    total: 3,
    rate: 0.33,
    avg: 0,
    samples: [],
    summary: '同类题里答错率偏高',
    ...overrides,
  } as WeaknessItem
}

function emptyLearn(): LearnProgressState {
  return { lastChapterId: null, chapters: {} }
}

describe('buildStudyPlan', () => {
  const modes: PlanMinutes[] = [15, 30, 60]

  it('旧报告（weakness_map=null）返回空计划，不编造任务', () => {
    const plan = buildStudyPlan(makeReport(null), { dailyMinutes: 30 })
    expect(plan.days).toEqual([])
    expect(plan.truncated).toBe(false)
  })

  it('无计分短板（weakness_map=[]）返回空计划', () => {
    const plan = buildStudyPlan(makeReport([]), { dailyMinutes: 30 })
    expect(plan.days).toEqual([])
  })

  it('三档时长都排满 7 天且每天不超预算', () => {
    const report = makeReport([
      weakness('事件循环', '前端'),
      weakness('索引失效', 'SQL 与数据库'),
      weakness('动态规划', '算法与数据结构'),
      weakness('进程与线程', '计算机基础'),
    ])
    for (const dailyMinutes of modes) {
      const plan = buildStudyPlan(report, { dailyMinutes, learned: emptyLearn() })
      expect(plan.days).toHaveLength(PLAN_DAY_COUNT)
      for (const day of plan.days) {
        expect(day.tasks.length).toBeGreaterThan(0)
        expect(day.minutes).toBeLessThanOrEqual(dailyMinutes)
        const sum = day.tasks.reduce((total, task) => total + task.est_min, 0)
        expect(day.minutes).toBe(sum)
      }
    }
  })

  it('r50 短板带二级方向时，专项练习链接带 sub 参数', () => {
    const report = makeReport([
      weakness('推理服务', 'AI 工程', { sub_direction: '部署与推理' }),
    ])
    const plan = buildStudyPlan(report, { dailyMinutes: 30, learned: emptyLearn() })
    const practice = plan.days
      .flatMap((day) => day.tasks)
      .find((task) => task.kind === 'practice' && task.shortfall !== null)
    expect(practice).toBeDefined()
    const query = new URLSearchParams((practice?.href ?? '').split('?')[1] ?? '')
    expect(query.get('direction')).toBe('AI 工程')
    expect(query.get('sub')).toBe('部署与推理')
  })

  it('r50 practiceHref 只在非空子方向写 sub（与练习页 ?sub= 同参数名）', () => {
    expect(practiceHref({ direction: 'AI 工程' })).not.toContain('sub=')
    expect(practiceHref({ direction: 'AI 工程', sub_direction: '' })).not.toContain('sub=')
    const query = new URLSearchParams(
      practiceHref({ direction: 'AI 工程', sub_direction: 'Agent' }).split('?')[1],
    )
    expect(query.get('sub')).toBe('Agent')
    expect(query.get('direction')).toBe('AI 工程')
  })

  it('短板不足 7 天时用通用任务补空天，且不编造短板名', () => {
    const report = makeReport([weakness('不存在的主题', '前端')])
    const plan = buildStudyPlan(report, { dailyMinutes: 30 })
    const fillers = plan.days.flatMap((day) => day.tasks).filter((task) => task.kind === 'review')
    expect(fillers.length).toBeGreaterThan(0)
    expect(fillers.every((task) => task.shortfall === null)).toBe(true)
    expect(fillers.every((task) => task.reason === '通用建议')).toBe(true)
  })

  it('权重高的短板排在更前面（严重度 + 必备度 + 错误率）', () => {
    const report = makeReport([
      weakness('低优先', '前端', {
        difficulty: ['basic'],
        essentiality: ['nice_to_have'],
        rate: 1,
      }),
      weakness('高优先', '后端', {
        difficulty: ['challenge'],
        essentiality: ['must_know'],
        rate: 0,
      }),
    ])
    const plan = buildStudyPlan(report, { dailyMinutes: 15 })
    const tasks = plan.days.flatMap((day) => day.tasks)
    const highIndex = tasks.findIndex((task) => task.shortfall === '高优先')
    const lowIndex = tasks.findIndex((task) => task.shortfall === '低优先')
    expect(highIndex).toBeGreaterThanOrEqual(0)
    expect(lowIndex).toBeGreaterThan(highIndex)
  })

  it('高级章未读时先插「前置：基础章」任务（难度递进代理）', () => {
    const advanced = ALL_TUTORIAL_CHAPTERS.find((chapter) => chapter.level === '高级')
    const base = ALL_TUTORIAL_CHAPTERS.find(
      (chapter) => chapter.direction === advanced?.direction && chapter.level === '基础',
    )
    expect(advanced).toBeDefined()
    expect(base).toBeDefined()
    const report = makeReport([
      weakness('高级知识薄弱', advanced!.direction, { difficulty: ['challenge'] }),
    ])
    const plan = buildStudyPlan(report, { dailyMinutes: 60, learned: emptyLearn() })
    const prereq = plan.days
      .flatMap((day) => day.tasks)
      .find((task) => task.reason.startsWith('前置'))
    expect(prereq).toBeDefined()
    expect(prereq?.chapter_id).toBe(base!.id)
  })

  it('整章已读后不再排该章教程，只留练题', () => {
    const advanced = ALL_TUTORIAL_CHAPTERS.find((chapter) => chapter.level === '高级')
    const base = ALL_TUTORIAL_CHAPTERS.find(
      (chapter) => chapter.direction === advanced?.direction && chapter.level === '基础',
    )
    const learned: LearnProgressState = {
      lastChapterId: advanced!.id,
      chapters: {
        [advanced!.id]: {
          seen: advanced!.sections.map((section) => section.id),
          lastSectionId: null,
          updatedAt: 0,
        },
        [base!.id]: {
          seen: base!.sections.map((section) => section.id),
          lastSectionId: null,
          updatedAt: 0,
        },
      },
    }
    const report = makeReport([
      weakness('高级知识薄弱', advanced!.direction, { difficulty: ['challenge'] }),
    ])
    const plan = buildStudyPlan(report, { dailyMinutes: 30, learned })
    const tasks = plan.days.flatMap((day) => day.tasks)
    expect(tasks.some((task) => task.chapter_id === advanced!.id)).toBe(false)
    expect(tasks.some((task) => task.kind === 'practice' && task.shortfall !== null)).toBe(true)
  })

  it('同方向同难度的短板只排一次教程与练题（去重）', () => {
    const report = makeReport([
      weakness('短板甲', '前端'),
      weakness('短板乙', '前端'),
    ])
    const plan = buildStudyPlan(report, { dailyMinutes: 60 })
    const ids = plan.days.flatMap((day) => day.tasks).map((task) => task.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('方向匹配不到教程时降级为练题 + 通用任务，链接仍可用', () => {
    const report = makeReport([weakness('冷门主题', '不存在方向')])
    const plan = buildStudyPlan(report, { dailyMinutes: 15 })
    const tasks = plan.days.flatMap((day) => day.tasks)
    expect(tasks.every((task) => task.href.startsWith('/'))).toBe(true)
    expect(tasks.some((task) => task.kind === 'practice' && task.shortfall === '冷门主题')).toBe(
      true,
    )
  })

  it('planStats 按任务粒度统计完成度', () => {
    const plan = buildStudyPlan(makeReport([weakness('事件循环', '前端')]), {
      dailyMinutes: 30,
    })
    const tasks = plan.days.flatMap((day) => day.tasks)
    const done = { [tasks[0].id]: true as const, [tasks[1].id]: true as const }
    const stats = planStats(plan, done)
    expect(stats.total).toBe(tasks.length)
    expect(stats.completed).toBe(2)
    expect(stats.percent).toBe(Math.round((2 / tasks.length) * 100))
  })
  it('r49：短板带子方向时优先选同子方向的高级章', () => {
    const serving = ALL_TUTORIAL_CHAPTERS.find(
      (chapter) => chapter.id === 'ai-inference-serving',
    )
    const directionFirst = ALL_TUTORIAL_CHAPTERS.find(
      (chapter) => chapter.direction === 'AI 工程' && chapter.level === '高级',
    )
    expect(serving).toBeDefined()
    expect(directionFirst?.id).not.toBe(serving!.id)
    const report = makeReport([
      weakness('推理服务不稳', 'AI 工程', {
        difficulty: ['challenge'],
        sub_direction: '部署与推理',
      }),
    ])
    const plan = buildStudyPlan(report, { dailyMinutes: 60, learned: emptyLearn() })
    const tutorials = plan.days
      .flatMap((day) => day.tasks)
      .filter((task) => task.kind === 'tutorial')
    expect(tutorials.some((task) => task.chapter_id === serving!.id)).toBe(true)
    expect(tutorials.some((task) => task.chapter_id === directionFirst!.id)).toBe(false)
  })

  it('r49：子方向暂无教程时逐字回落到方向级选章', () => {
    const ids = (plan: ReturnType<typeof buildStudyPlan>) =>
      plan.days
        .flatMap((day) => day.tasks)
        .filter((task) => task.kind === 'tutorial')
        .map((task) => task.id)
    const plain = buildStudyPlan(makeReport([weakness('HTML 语义化', '前端')]), {
      dailyMinutes: 60,
      learned: emptyLearn(),
    })
    const tagged = buildStudyPlan(
      makeReport([weakness('HTML 语义化', '前端', { sub_direction: 'html' })]),
      { dailyMinutes: 60, learned: emptyLearn() },
    )
    expect(ids(plain).length).toBeGreaterThan(0)
    expect(ids(tagged)).toEqual(ids(plain))
    expect(ids(tagged).every((id) => id.startsWith('tutorial:'))).toBe(true)
  })

  it('r49：子方向内没有目标档位时按难度递进取该子方向的低档章', () => {
    const chapter = ALL_TUTORIAL_CHAPTERS.find(
      (item) => item.id === 'ai-prompt-engineering',
    )
    expect(chapter?.level).toBe('进阶')
    const report = makeReport([
      weakness('提示词漂移', 'AI 工程', {
        difficulty: ['challenge'],
        sub_direction: 'Prompt 工程',
      }),
    ])
    const plan = buildStudyPlan(report, { dailyMinutes: 60, learned: emptyLearn() })
    const tutorials = plan.days
      .flatMap((day) => day.tasks)
      .filter((task) => task.kind === 'tutorial')
    expect(tutorials.some((task) => task.chapter_id === 'ai-prompt-engineering')).toBe(true)
  })
})

describe('计划本地存储的解析', () => {
  it('坏 JSON / 非法版本 / 非法时长一律退回 null', () => {
    expect(parsePlanState('{oops')).toBeNull()
    expect(parsePlanState(JSON.stringify({ version: 2, daily_minutes: 30, done: {} }))).toBeNull()
    expect(
      parsePlanState(JSON.stringify({ version: 1, daily_minutes: 45, done: {} })),
    ).toBeNull()
    expect(parseStoredPlan(JSON.stringify({ version: 9, days: [] }))).toBeNull()
  })

  it('只保留 done=true 的打卡项', () => {
    const state = parsePlanState(
      JSON.stringify({
        version: 1,
        daily_minutes: 15,
        done: { a: true, b: false, c: true },
      }),
    )
    expect(state?.done).toEqual({ a: true, c: true })
    expect(state?.daily_minutes).toBe(15)
  })

  it('计划快照可原样读回（version / 时长 / 结构校验）', () => {
    const plan = buildStudyPlan(makeReport([weakness('事件循环', '前端')]), { dailyMinutes: 60 })
    expect(parseStoredPlan(JSON.stringify(plan))).toEqual(plan)
  })
})
