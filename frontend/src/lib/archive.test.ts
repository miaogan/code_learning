import { describe, expect, it } from 'vitest'

import type { Profile, Report, ResumeVersionSummary, RunSummary, WeaknessItem } from '../api/types'
import {
  ARCHIVE_PREFIX,
  archiveFileName,
  archiveMarkdown,
  buildArchiveSnapshot,
  isEmptyArchive,
  MAX_ARCHIVE_WEAKNESSES,
  type ArchiveInput,
} from './archive'
import { EMPTY_LEARN_PROGRESS, type LearnProgressState } from './learnProgress'
import { ALL_TUTORIAL_CHAPTERS } from './tutorials'
import { PLAN_VERSION, type StudyPlan, type StudyTask } from './studyPlan'

const NOW = new Date('2026-11-10T09:30:00')

function profile(overrides: Partial<Profile> = {}): Profile {
  return {
    id: 'p1',
    resume_id: 'r1',
    updated_at: '2026-11-08T02:00:00Z',
    skills: [
      { name: 'Python', source_quote: 'Python', status: 'active' },
      { name: '旧技能', source_quote: '旧技能', status: 'historical' },
    ],
    tech_stack: ['FastAPI', ''],
    years_experience: 3,
    projects: [
      {
        name: '项目 A',
        role: '后端',
        period: null,
        bullets: [],
        source_quote: '项目 A',
        status: 'active',
      },
      {
        name: '项目 B',
        role: null,
        period: null,
        bullets: [],
        source_quote: '项目 B',
        status: 'historical',
      },
    ],
    target_role: '后端工程师',
    ...overrides,
  }
}

function run(id: string, kind: 'interview' | 'exam', score: number | null): RunSummary {
  return {
    id,
    kind,
    score,
    shortfall_count: null,
    created_at: '2026-11-09T04:00:00Z',
    interview_settings: null,
  }
}

function weakness(overrides: Partial<WeaknessItem> = {}): WeaknessItem {
  return {
    key: 'k',
    point: 'React 渲染',
    direction: '前端',
    sub_direction: '',
    wrong: 1,
    total: 2,
    rate: 0.5,
    avg: 0,
    difficulty: [],
    essentiality: [],
    samples: [],
    note: '',
    ...overrides,
  } as WeaknessItem
}

function report(items: WeaknessItem[] | null): Report {
  return {
    id: 'rep1',
    run_ids: ['r1'],
    interview_avg: 7,
    exam_total: null,
    shortfalls: [],
    generated_at: '2026-11-09T05:00:00Z',
    interview_settings: null,
    weakness_map: items,
    resume_pointers: null,
    resume_pointers_notice: null,
    role_fit: null,
  }
}

function version(id: string, createdAt: string): ResumeVersionSummary {
  return {
    resume_id: id,
    file_name: `${id}.pdf`,
    source_type: 'pdf',
    chars: 12345,
    sections: 6,
    created_at: createdAt,
    has_profile: true,
    interview_avg: null,
    exam_total: null,
    judged_count: 0,
  }
}

function task(id: string, title: string, kind: StudyTask['kind']): StudyTask {
  return {
    id,
    kind,
    title,
    est_min: 15,
    direction: null,
    chapter_id: null,
    section_id: null,
    href: '/learn',
    reason: '',
    shortfall: null,
  }
}

function plan(): StudyPlan {
  return {
    version: PLAN_VERSION,
    report_id: 'rep1',
    daily_minutes: 30,
    truncated: false,
    updated_at: '2026-11-09T05:00:00Z',
    days: [
      {
        day: 1,
        minutes: 30,
        tasks: [task('t1', '看一章', 'tutorial'), task('t2', '练一组', 'practice')],
      },
      { day: 2, minutes: 15, tasks: [task('t3', '复习', 'review')] },
    ],
  }
}

function progressOfFirstChapter(): LearnProgressState {
  const chapter = ALL_TUTORIAL_CHAPTERS[0]
  return {
    lastChapterId: chapter.id,
    chapters: {
      [chapter.id]: {
        seen: chapter.sections.map((section) => section.id),
        lastSectionId: chapter.sections[chapter.sections.length - 1]?.id ?? null,
        updatedAt: 1,
      },
    },
  }
}

function input(overrides: Partial<ArchiveInput> = {}): ArchiveInput {
  return {
    profile: profile(),
    versions: [version('v2', '2026-11-08T02:00:00Z'), version('v1', '2026-11-01T02:00:00Z')],
    runs: [run('i2', 'interview', 8), run('e1', 'exam', 75), run('i1', 'interview', null)],
    report: report([weakness()]),
    progress: progressOfFirstChapter(),
    plan: plan(),
    planDone: { t1: true } as Record<string, true>,
    ...overrides,
  }
}

describe('buildArchiveSnapshot', () => {
  it('画像只数 active 项，并过滤空技术栈', () => {
    const snapshot = buildArchiveSnapshot(input())
    expect(snapshot.profile?.skills).toEqual(['Python'])
    expect(snapshot.profile?.tech).toEqual(['FastAPI'])
    expect(snapshot.profile?.projects).toBe(1)
    expect(snapshot.profile?.years).toBe(3)
  })

  it('成绩跳过一题未答的 null 记录，取第一条有分记录', () => {
    const snapshot = buildArchiveSnapshot(input())
    expect(snapshot.scores.interviewCount).toBe(2)
    expect(snapshot.scores.examCount).toBe(1)
    expect(snapshot.scores.judgedCount).toBe(2)
    expect(snapshot.scores.latestInterview).toBe(8)
    expect(snapshot.scores.latestExam).toBe(75)
  })

  it('没有报告时 weakness 为空且标记不可用', () => {
    const snapshot = buildArchiveSnapshot(input({ report: null }))
    expect(snapshot.weaknesses).toEqual([])
    expect(snapshot.weaknessesAvailable).toBe(false)
    expect(snapshot.reportAt).toBeNull()
  })

  it('weakness 过滤 total=0 并按错误率 / 错题数降序，最多 5 条', () => {
    const items = [
      weakness({ direction: 'A', rate: 0.4, wrong: 2, total: 5 }),
      weakness({ direction: 'B', rate: 0.4, wrong: 3, total: 5 }),
      weakness({ direction: 'C', rate: 0.8, wrong: 4, total: 5 }),
      weakness({ direction: 'D', rate: 0, wrong: 0, total: 0 }),
      weakness({ direction: 'E', rate: 0.2, wrong: 1, total: 5 }),
      weakness({ direction: 'F', rate: 0.6, wrong: 3, total: 5 }),
      weakness({ direction: 'G', rate: 0.1, wrong: 1, total: 10 }),
    ]
    const snapshot = buildArchiveSnapshot(input({ report: report(items) }))
    expect(snapshot.weaknesses.map((item) => item.direction)).toEqual(['C', 'F', 'B', 'A', 'E'])
    expect(snapshot.weaknesses).toHaveLength(MAX_ARCHIVE_WEAKNESSES)
  })

  it('学习进度映射到汇总数字（读完一章 = 1 章）', () => {
    const empty = buildArchiveSnapshot(input({ progress: EMPTY_LEARN_PROGRESS }))
    expect(empty.learn.done).toBe(0)
    expect(empty.learn.chapters).toBe(ALL_TUTORIAL_CHAPTERS.length)

    const snapshot = buildArchiveSnapshot(input())
    expect(snapshot.learn.done).toBe(1)
    expect(snapshot.learn.reading).toBe(0)
    expect(snapshot.learn.percent).toBeGreaterThan(0)
  })

  it('计划打卡只数 true 条目', () => {
    const snapshot = buildArchiveSnapshot(input())
    expect(snapshot.plan).toEqual({ total: 3, completed: 1, percent: 33 })
  })

  it('没有计划时 plan 为 null（不是 0%）', () => {
    const snapshot = buildArchiveSnapshot(input({ plan: null }))
    expect(snapshot.plan).toBeNull()
  })

  it('空输入不走空态判定以外的分支', () => {
    const snapshot = buildArchiveSnapshot(
      input({
        profile: null,
        versions: [],
        runs: [],
        report: null,
        progress: EMPTY_LEARN_PROGRESS,
        plan: null,
      }),
    )
    expect(isEmptyArchive(snapshot)).toBe(true)
    expect(snapshot.versions.latest).toBeNull()
  })
})

describe('archiveMarkdown', () => {
  it('包含六个小节与实测数字', () => {
    const text = archiveMarkdown(buildArchiveSnapshot(input()), NOW)
    expect(text).toContain('# 学习档案')
    expect(text).toContain('生成时间：2026-11-10 09:30')
    expect(text).toContain('## 目标与画像')
    expect(text).toContain('- 目标岗位：后端工程师')
    expect(text).toContain('- 面试最近一次：8 / 10')
    expect(text).toContain('- 笔试最近一次：75 / 100')
    expect(text).toContain('## 薄弱方向')
    expect(text).toContain('前端：错 1 / 2 题，错误率 50%')
    expect(text).toContain('## 学习进度')
    expect(text).toContain('- 已完成 1 / 3 个任务（33%）')
    expect(text).toContain('不代表能力评级或求职结果')
  })

  it('空档案给「为什么空 / 怎么补」的中文说明，不出现 null / undefined', () => {
    const snapshot = buildArchiveSnapshot(
      input({
        profile: null,
        versions: [],
        runs: [],
        report: null,
        progress: EMPTY_LEARN_PROGRESS,
        plan: null,
      }),
    )
    const text = archiveMarkdown(snapshot, NOW)
    expect(text).toContain('还没有技术画像')
    expect(text).toContain('还没有已计分的测评记录')
    expect(text).toContain('还没有简历版本')
    expect(text).toContain('还没有诊断报告')
    expect(text).toContain('还没有可用的 7 天计划')
    expect(text).not.toContain('null')
    expect(text).not.toContain('undefined')
  })

  it('报告存在但无已计分题时与「没有报告」区分文案', () => {
    const empty = archiveMarkdown(buildArchiveSnapshot(input({ report: report([]) })), NOW)
    expect(empty).toContain('本次报告里没有形成薄弱方向')
  })

  it('坐标不足 1 条薄弱方向时不带序号以外的假数据', () => {
    const text = archiveMarkdown(buildArchiveSnapshot(input({ report: report(null) })), NOW)
    expect(text).toContain('还没有诊断报告')
  })
})

describe('archiveFileName', () => {
  it('按本地日期命名', () => {
    expect(archiveFileName(NOW)).toBe(`${ARCHIVE_PREFIX}2026-11-10.md`)
  })

  it('跨月补零', () => {
    expect(archiveFileName(new Date('2026-01-05T10:00:00'))).toBe(`${ARCHIVE_PREFIX}2026-01-05.md`)
  })
})
