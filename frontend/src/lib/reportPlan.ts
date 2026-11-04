/**
 * 报告页「7 天补短板计划」的纯逻辑（无 DOM / 无请求，vitest 直接断言）。
 *
 * 计划只投影报告里已有的真实数据：薄弱分组决定练习筛选，短板挂的课程决定当天读什么。
 * **不发明题库里没有的「公司高频题」标签** —— 计划里的每个任务都可回到真实题目或真实课程。
 */
import type { Course, Report, WeaknessItem } from '../api/types'
import { DIFFICULTY_LABEL, ESSENTIALITY_LABEL } from './practice'

/** 计划固定 7 天：前 3 天补最靠前的薄弱分组，后 4 天固定为错题 / 综合 / 模拟。 */
export const PLAN_DAY_COUNT = 7
/** 前 N 天按薄弱分组排（与报告薄弱地图的前三名一致）。 */
const FOCUS_DAY_COUNT = 3

export type PlanTaskKind = 'practice' | 'course' | 'mock'

export interface PlanTask {
  id: string
  kind: PlanTaskKind
  label: string
  /** 站内链接；无链接的任务（课程没有 url 时）为 `null`，渲染成纯文本。 */
  href: string | null
  /** 一行元信息（方向 / 难度 / 课程级别等），全部取自真实字段。 */
  meta: string
}

export interface PlanDay {
  day: number
  title: string
  focus: string
  tasks: PlanTask[]
}

/** 旧报告（`weakness_map === null`）无法按薄弱分组排计划，只提示重新生成。 */
export const PLAN_LEGACY_NOTICE = '旧报告不含薄弱地图，重新生成后可生成按薄弱分组的学习计划'
/** 新报告但本次没有可排的计分短板。 */
export const PLAN_EMPTY_NOTICE = '本次测评还没有可排入计划的短板，完成一轮有计分的测评后再来'

/** 薄弱分组的难度 / 必备度可能多值：只有唯一值时才收窄筛选，否则保持「全部」。 */
function filterValue(values: string[]): string {
  return values.length === 1 ? values[0] : 'all'
}

function labelOf(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

/** 拼 `/practice` 链接：只写真实生效的筛选参数（默认值不写，链接更短也更好读）。 */
export function practiceHref(params: {
  direction?: string | null
  difficulty?: string | null
  essentiality?: string | null
  scope?: string | null
  limit?: number | null
}): string {
  const query = new URLSearchParams()
  if (params.direction !== null && params.direction !== undefined && params.direction !== 'all') {
    query.set('direction', params.direction)
  }
  if (
    params.difficulty !== null &&
    params.difficulty !== undefined &&
    params.difficulty !== 'all'
  ) {
    query.set('difficulty', params.difficulty)
  }
  if (
    params.essentiality !== null &&
    params.essentiality !== undefined &&
    params.essentiality !== 'all'
  ) {
    query.set('essentiality', params.essentiality)
  }
  if (params.scope !== null && params.scope !== undefined && params.scope !== 'all') {
    query.set('scope', params.scope)
  }
  if (params.limit !== null && params.limit !== undefined) query.set('limit', String(params.limit))
  const suffix = query.toString()
  return suffix === '' ? '/practice' : `/practice?${suffix}`
}

/** 报告里所有短板的课程去重（同一门课可能挂在多条短板上，避免计划重复推荐）。 */
function uniqueCourses(report: Report): Course[] {
  const seen = new Set<string>()
  const courses: Course[] = []
  report.shortfalls.forEach((shortfall) => {
    shortfall.courses.forEach((course) => {
      if (seen.has(course.id)) return
      seen.add(course.id)
      courses.push(course)
    })
  })
  return courses
}

function metaOf(direction: string, difficulty: string, essentiality: string): string {
  const parts = [direction]
  if (difficulty !== 'all') parts.push(labelOf(DIFFICULTY_LABEL, difficulty))
  if (essentiality !== 'all') parts.push(labelOf(ESSENTIALITY_LABEL, essentiality))
  return parts.join(' · ')
}

function courseTask(course: Course, day: number, index: number): PlanTask {
  return {
    id: `day-${day}-course-${course.id}-${index}`,
    kind: 'course',
    label: course.title,
    href: course.url,
    meta: `${course.direction} · ${course.level}`,
  }
}

function focusDay(day: number, item: WeaknessItem, courses: Course[]): PlanDay {
  const difficulty = filterValue(item.difficulty)
  const essentiality = filterValue(item.essentiality)
  const practice: PlanTask = {
    id: `day-${day}-practice`,
    kind: 'practice',
    label: '专项练习 10 题',
    href: practiceHref({
      direction: item.direction,
      difficulty,
      essentiality,
      limit: 10,
    }),
    meta: metaOf(item.direction, difficulty, essentiality),
  }
  // 优先同方向课程；同方向没有课时退到报告里的第一门（不硬造不存在的课程）。
  const matched = courses.filter((course) => course.direction === item.direction).slice(0, 2)
  const picked = matched.length > 0 ? matched : courses.slice(0, 1)
  return {
    day,
    title: `补短板 · ${item.point}`,
    focus: item.summary,
    tasks: [practice, ...picked.map((course, index) => courseTask(course, day, index))],
  }
}

function generalDay(day: number, limit: number): PlanDay {
  return {
    day,
    title: '综合练习',
    focus: limit === 10 ? '先用 10 题热身，把做题手感找回来' : '加练到 20 题，检验这一周补课的效果',
    tasks: [
      {
        id: `day-${day}-practice`,
        kind: 'practice',
        label: `综合练习 ${limit} 题`,
        href: practiceHref({ limit }),
        meta: '全部方向 · 全部难度',
      },
    ],
  }
}

function tailDays(): PlanDay[] {
  return [
    {
      day: 4,
      title: '错题清零',
      focus: '把最近一轮答错的题全部重做，答对一次即移出错题本',
      tasks: [
        {
          id: 'day-4-practice',
          kind: 'practice',
          label: '错题重练（全部）',
          href: practiceHref({ scope: 'wrong', limit: 0 }),
          meta: '只看错题 · 全部题量',
        },
      ],
    },
    {
      day: 5,
      title: '综合练习',
      focus: '不限方向再刷一轮，检验补课效果',
      tasks: [
        {
          id: 'day-5-practice',
          kind: 'practice',
          label: '综合练习 20 题',
          href: practiceHref({ limit: 20 }),
          meta: '全部方向 · 全部难度',
        },
      ],
    },
    {
      day: 6,
      title: '模拟笔试',
      focus: '按真实节奏完整做一套客观题，看正确率有没有抬上来',
      tasks: [
        {
          id: 'day-6-exam',
          kind: 'mock',
          label: '去模拟笔试',
          href: '/exam',
          meta: '客观题 · 即时判分',
        },
      ],
    },
    {
      day: 7,
      title: '模拟面试 + 复盘',
      focus: '完成一场模拟面试，再重新生成诊断报告对照短板变化',
      tasks: [
        {
          id: 'day-7-interview',
          kind: 'mock',
          label: '去模拟面试',
          href: '/interview',
          meta: '逐题作答 · AI 点评',
        },
        {
          id: 'day-7-report',
          kind: 'mock',
          label: '重新生成诊断报告',
          href: '/report',
          meta: '对照本周变化',
        },
      ],
    },
  ]
}

/**
 * 生成固定 7 天的计划。
 * `weakness_map === null`（旧报告）或 `[]`（本次无计分题）时返回空数组，由调用方展示对应提示。
 */
export function buildWeekPlan(report: Report): PlanDay[] {
  if (report.weakness_map === null || report.weakness_map.length === 0) return []
  const courses = uniqueCourses(report)
  const days: PlanDay[] = []
  report.weakness_map.slice(0, FOCUS_DAY_COUNT).forEach((item) => {
    days.push(focusDay(days.length + 1, item, courses))
  })
  while (days.length < FOCUS_DAY_COUNT) {
    days.push(generalDay(days.length + 1, days.length === 1 ? 10 : 20))
  }
  return [...days, ...tailDays()]
}

/** 打卡状态按「账号 + 报告」分开存：换账号 / 新报告不会继承上一个人的进度。 */
export function weekPlanStorageKey(userId: string, reportId: string): string {
  return `weekplan:${userId}:${reportId}`
}

/** 解析本地打卡记录（`[1,2]`）：非数组 / 非法 JSON / 越界天数一律丢弃，坏数据不炸页面。 */
export function parsePlanProgress(raw: string | null): number[] {
  if (raw === null) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const days = parsed.filter(
      (value): value is number =>
        typeof value === 'number' &&
        Number.isInteger(value) &&
        value >= 1 &&
        value <= PLAN_DAY_COUNT,
    )
    return Array.from(new Set(days)).sort((a, b) => a - b)
  } catch {
    return []
  }
}
