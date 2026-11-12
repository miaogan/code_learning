import { describe, expect, it } from 'vitest'
import type { Report, WeaknessItem } from '../api/types'
import { ALL_TUTORIAL_CHAPTERS } from '../lib/tutorials'
import type { LearnProgressState } from '../lib/learnProgress'
import {
  PLAN_DAY_COUNT,
  PLAN_VERSION,
  buildStudyPlan,
  dayOffset,
  isoDay,
  mergePlanState,
  parsePlanState,
  parseStoredPlan,
  planPace,
  planPushPayload,
  planStats,
  practiceHref,
  resumeDay,
  samePlanState,
  shiftDay,
  type PlanMinutes,
  type PlanState,
  type StudyPlan,
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

/* ---------- r61 打卡上云：上推载荷与跨设备合并 ---------- */

function planState(dailyMinutes: PlanMinutes, done: Record<string, true>): PlanState {
  return { version: PLAN_VERSION, daily_minutes: dailyMinutes, done, started_on: '' }
}

describe('打卡上云载荷', () => {
  it('只带 true 条目（取消打卡不在 map 里）', () => {
    const payload = planPushPayload(planState(30, { a: true, c: true }))
    expect(payload).toEqual({ daily_minutes: 30, done: { a: true, c: true }, started_on: '' })
    expect(JSON.stringify(payload)).not.toContain('false')
  })
})

describe('打卡状态跨设备合并', () => {
  it('云端没有记录时保留本机时长与打卡（首次上云）', () => {
    const merged = mergePlanState(planState(60, { a: true }), {
      daily_minutes: 30,
      done: {},
      updated_at: '',
    })
    expect(merged.daily_minutes).toBe(60)
    expect(merged.done).toEqual({ a: true })
  })

  it('云端有记录时时长以云端为准，打卡取并集', () => {
    const merged = mergePlanState(planState(15, { a: true }), {
      daily_minutes: 60,
      done: { b: true, c: false },
      updated_at: '2026-11-10T00:00:00+00:00',
    })
    expect(merged.daily_minutes).toBe(60)
    expect(merged.done).toEqual({ a: true, b: true })
    expect(merged.version).toBe(PLAN_VERSION)
  })
})

describe('打卡状态等价判断', () => {
  it('键集合与时长一致即等价，false 残留不影响', () => {
    expect(
      samePlanState(planState(30, { a: true }), { daily_minutes: 30, done: { a: true, b: false } }),
    ).toBe(true)
  })

  it('时长或多出一个已打卡项都算有差异', () => {
    expect(samePlanState(planState(30, { a: true }), { daily_minutes: 15, done: { a: true } })).toBe(false)
    expect(samePlanState(planState(30, { a: true }), { daily_minutes: 30, done: { a: true, b: true } })).toBe(false)
  })
})

/* ---------- r95 计划按日历推进 ---------- */

function stubPlan(): StudyPlan {
  return {
    version: PLAN_VERSION,
    report_id: 'report-1',
    daily_minutes: 30,
    days: Array.from({ length: PLAN_DAY_COUNT }, (_, index) => ({
      day: index + 1,
      minutes: 15,
      tasks: [
        {
          id: `t${index + 1}`,
          kind: 'review' as const,
          title: '读一节',
          est_min: 15,
          direction: null,
          chapter_id: null,
          section_id: null,
          href: '/learn',
          reason: '通用建议',
          shortfall: null,
        },
      ],
    })),
    truncated: false,
    updated_at: '',
  }
}

describe('日历日工具', () => {
  it('isoDay 取本机日历日（不是 UTC，凌晨不差一天）', () => {
    expect(isoDay(new Date(2026, 10, 12, 0, 30))).toBe('2026-11-12')
    expect(isoDay(new Date(2026, 0, 1, 23, 59))).toBe('2026-01-01')
  })

  it('shiftDay 跨月跨年正确，坏值返回 null', () => {
    expect(shiftDay('2026-11-30', 1)).toBe('2026-12-01')
    expect(shiftDay('2026-01-01', -1)).toBe('2025-12-31')
    expect(shiftDay('2026-03-01', -1)).toBe('2026-02-28')
    expect(shiftDay('2026-02-31', 0)).toBeNull()
    expect(shiftDay('2026/11/12', 1)).toBeNull()
  })

  it('dayOffset 只按日历日算差值', () => {
    expect(dayOffset('2026-11-12', '2026-11-12')).toBe(0)
    expect(dayOffset('2026-11-30', '2026-12-03')).toBe(3)
    expect(dayOffset('2026-12-03', '2026-11-30')).toBe(-3)
    expect(dayOffset('', '2026-11-12')).toBeNull()
  })
})

describe('计划与今天对齐', () => {
  it('没开始计时：不标今天、也不算落后', () => {
    const pace = planPace(stubPlan(), {}, '', '2026-11-12')
    expect(pace.started).toBe(false)
    expect(pace.todayDay).toBeNull()
    expect(pace.behindDays).toBe(0)
    expect(pace.firstOpenDay).toBe(1)
  })

  it('第 2 天且 Day 1 已做完：今天=2、没落后', () => {
    const pace = planPace(stubPlan(), { t1: true }, '2026-11-11', '2026-11-12')
    expect(pace).toMatchObject({ started: true, todayDay: 2, expired: false, behindDays: 0 })
    expect(pace.firstOpenDay).toBe(2)
  })

  it('第 3 天但 Day 1 没做完：落后 1 天', () => {
    const pace = planPace(stubPlan(), { t2: true }, '2026-11-10', '2026-11-12')
    expect(pace.todayDay).toBe(3)
    expect(pace.behindDays).toBe(1)
    expect(pace.firstOpenDay).toBe(1)
  })

  it('7 天走完：过期、今天不再是第 7 天，落后按全部未完成天算', () => {
    const pace = planPace(stubPlan(), { t1: true, t2: true }, '2026-11-01', '2026-11-12')
    expect(pace.expired).toBe(true)
    expect(pace.todayDay).toBeNull()
    expect(pace.behindDays).toBe(5)
  })

  it('时钟回拨（起始日在未来）按第 1 天处理，不出现负数天', () => {
    const pace = planPace(stubPlan(), {}, '2026-11-20', '2026-11-12')
    expect(pace.todayDay).toBe(1)
    expect(pace.behindDays).toBe(0)
    expect(pace.expired).toBe(false)
  })

  it('顺延：把第一个没做完的天挪到今天', () => {
    expect(resumeDay(3, '2026-11-12')).toBe('2026-11-10')
    expect(resumeDay(1, '2026-11-12')).toBe('2026-11-12')
    expect(resumeDay(0, '2026-11-12')).toBeNull()
  })
})

describe('起始日跨设备', () => {
  it('云端起始日优先；云端为空时保留本机刚点的「今天开始」', () => {
    const local = { ...planState(30, {}), started_on: '2026-11-12' }
    expect(
      mergePlanState(local, {
        daily_minutes: 30,
        done: {},
        started_on: '2026-11-01',
        updated_at: '2026-11-10T00:00:00+00:00',
      }).started_on,
    ).toBe('2026-11-01')
    expect(
      mergePlanState(local, {
        daily_minutes: 30,
        done: { t1: true },
        started_on: '',
        updated_at: '2026-11-10T00:00:00+00:00',
      }).started_on,
    ).toBe('2026-11-12')
  })

  it('起始日进上推载荷；坏值落空串', () => {
    expect(planPushPayload({ ...planState(30, {}), started_on: '2026-11-12' }).started_on).toBe(
      '2026-11-12',
    )
    expect(planPushPayload({ ...planState(30, {}), started_on: '2026-02-31' }).started_on).toBe('')
  })

  it('起始日不同算有差异；本地缓存里的坏日期读回即丢弃', () => {
    expect(
      samePlanState(
        { daily_minutes: 30, done: {}, started_on: '2026-11-12' },
        { daily_minutes: 30, done: {}, started_on: '2026-11-11' },
      ),
    ).toBe(false)
    expect(
      parsePlanState(JSON.stringify({ ...planState(30, {}), started_on: '2026-13-01' }))?.started_on,
    ).toBe('')
    expect(
      parsePlanState(JSON.stringify({ ...planState(30, {}), started_on: '2026-11-12' }))?.started_on,
    ).toBe('2026-11-12')
  })
})
