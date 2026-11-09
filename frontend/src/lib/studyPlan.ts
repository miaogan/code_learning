/**
 * 报告 → 7 天可执行学习计划（r41 功能 B，B1 纯前端确定性排程）。
 *
 * 输入只有三份真实数据：报告里的薄弱地图、站内教程目录、本地已读小节；
 * 输出是可单测、可重算的固定 7 天任务表。**不调接口、不调 AI、不计入任何成绩**。
 *
 * 三条不能破的口径：
 * 1. 任务只能指回站内真实入口（教程章节 / 小节、练习筛选、模拟笔试面试）；
 * 2. 短板不足时用通用任务补位，**绝不编造短板名**；
 * 3. 教程章有「方向 / 子方向 / 难度」但没有显式前置字段 —— 「先读基础章」是**难度递进代理**，
 *    UI 文案不得宣称那是真实课程依赖；短板带子方向时优先选同子方向章，挑不到静默回落方向级。
 */
import type { Report, WeaknessItem } from '../api/types'
import type { LearnProgressState } from './learnProgress'
import type { TutorialChapter, TutorialLevel } from './tutorialTypes'
import { chaptersInDirection } from './tutorials'
import { DIFFICULTY_LABEL, ESSENTIALITY_LABEL } from './practice'

export const PLAN_DAY_COUNT = 7
export const PLAN_VERSION = 1 as const

/** 每日可用时长（分钟）：三档闭集，与 UI 选择器、存储校验共用一处。 */
export type PlanMinutes = 15 | 30 | 60
export const PLAN_MINUTES: PlanMinutes[] = [15, 30, 60]

export type TaskKind = 'tutorial' | 'practice' | 'review'

export interface StudyTask {
  /** 稳定 id：`tutorial:<chapter>:<section>` / `practice:...` / `review:<slug>:d<n>`。 */
  id: string
  kind: TaskKind
  title: string
  est_min: number
  direction: string | null
  chapter_id: string | null
  section_id: string | null
  href: string
  /** 一句话解释「为什么排这个」：短板名 / 前置 / 通用建议。 */
  reason: string
  shortfall: string | null
}

export interface StudyDay {
  day: number
  minutes: number
  tasks: StudyTask[]
}

export interface StudyPlan {
  version: typeof PLAN_VERSION
  report_id: string
  daily_minutes: PlanMinutes
  days: StudyDay[]
  /** 7 天装不下时截断（末日卡片据此提示「本周排不完，下周继续」）。 */
  truncated: boolean
  updated_at: string
}

/** 打卡与时长偏好：与计划快照分开存，重算计划时已完成的 task.id 不会被覆盖。 */
export interface PlanState {
  version: typeof PLAN_VERSION
  daily_minutes: PlanMinutes
  done: Record<string, true>
}

export const PLAN_LEGACY_NOTICE = '旧报告不含薄弱地图，重新生成后可生成按短板排的学习计划'
export const PLAN_EMPTY_NOTICE = '本次测评还没有可排入计划的短板，完成一轮有计分的测评后再来'
/** 必须在界面上明说：计划与打卡都在本机，不跨设备；且不进评分。 */
export const PLAN_LOCAL_ONLY_NOTICE =
  '计划与打卡只保存在这台设备的浏览器里：换设备或换浏览器看不到，也不会同步。打卡只记「做完」，不计入熟练度或成绩。'

const LEVEL_ORDER: Record<TutorialLevel, number> = { 基础: 0, 进阶: 1, 高级: 2 }

/** 难度档位 → 教程难度档（用于「先读基础章」的代理，不是真实课程依赖）。 */
const LEVEL_BY_DIFFICULTY: Record<string, TutorialLevel> = {
  basic: '基础',
  intermediate: '进阶',
  challenge: '高级',
}

const DIFFICULTY_RANK: Record<string, number> = { basic: 1, intermediate: 2, challenge: 3 }

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

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
  /** r50：二级方向聚焦；空串 / null = 不聚焦，URL 用 `sub`（与学习目录页同参数名）。 */
  sub_direction?: string | null
  difficulty?: string | null
  essentiality?: string | null
  scope?: string | null
  limit?: number | null
}): string {
  const query = new URLSearchParams()
  if (params.direction !== null && params.direction !== undefined && params.direction !== 'all') {
    query.set('direction', params.direction)
  }
  if (params.sub_direction !== null && params.sub_direction !== undefined && params.sub_direction !== '') {
    query.set('sub', params.sub_direction)
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

/** 权重：必备度 × 2 + 难度 + 错误率，全部来自报告已有字段。 */
function weightOf(item: WeaknessItem): number {
  const essential = item.essentiality.includes('must_know')
    ? 3
    : item.essentiality.includes('recommended')
      ? 2
      : 1
  const difficulty = item.difficulty.reduce(
    (max, value) => Math.max(max, DIFFICULTY_RANK[value] ?? 1),
    1,
  )
  return essential * 2 + difficulty + (1 - clamp01(item.rate)) * 2
}

function targetLevel(item: WeaknessItem): TutorialLevel {
  const ranked = [...item.difficulty].sort(
    (a, b) => (DIFFICULTY_RANK[b] ?? 1) - (DIFFICULTY_RANK[a] ?? 1),
  )
  return LEVEL_BY_DIFFICULTY[ranked[0] ?? 'basic'] ?? '基础'
}

function seenCount(learned: LearnProgressState | undefined, chapterId: string): number {
  return learned?.chapters[chapterId]?.seen.length ?? 0
}

/** 在一组章节里按「目标档位 → 就近低档 → 任意章」取章，纯确定性。 */
function pickInScope(chapters: TutorialChapter[], level: TutorialLevel): TutorialChapter | null {
  if (chapters.length === 0) return null
  const exact = chapters.find((chapter) => chapter.level === level)
  if (exact !== undefined) return exact
  const lower = [...chapters]
    .filter((chapter) => LEVEL_ORDER[chapter.level] < LEVEL_ORDER[level])
    .sort((a, b) => LEVEL_ORDER[b.level] - LEVEL_ORDER[a.level])
  return lower[0] ?? chapters[0]
}

/**
 * r49：短板带子方向时，先在该方向的同子方向章节里挑，挑不到再回落方向级。
 *
 * 分组键、任务 id 形态与「无子方向」时的逐章顺序都不变 —— 旧报告 / 老 payload
 * 缺 `sub_direction` 时走的就是原来那条方向级分支，结果逐字节可复算。
 * 回落是静默的：教程任务仍指回站内真实章节，不编造不存在的子方向章节。
 */
function pickChapter(
  direction: string,
  level: TutorialLevel,
  subDirection?: string,
): TutorialChapter | null {
  const chapters = chaptersInDirection(direction)
  if (chapters.length === 0) return null
  const sub = (subDirection ?? '').trim()
  if (sub !== '') {
    const focused = pickInScope(
      chapters.filter((chapter) => chapter.sub_direction === sub),
      level,
    )
    if (focused !== null) return focused
  }
  return pickInScope(chapters, level)
}

function tutorialMinutes(minutes: PlanMinutes): number {
  return minutes === 15 ? 15 : minutes === 30 ? 20 : 30
}

function practiceMinutes(minutes: PlanMinutes): number {
  return minutes === 15 ? 15 : minutes === 30 ? 15 : 20
}

function reviewMinutes(minutes: PlanMinutes): number {
  return minutes === 15 ? 10 : minutes === 30 ? 10 : 15
}

function tutorialHref(chapterId: string, sectionId: string): string {
  return `/learn/${chapterId}#tutorial-${sectionId}`
}

function tutorialTask(
  chapter: TutorialChapter,
  sectionId: string,
  minutes: PlanMinutes,
  reason: string,
  shortfall: string | null,
): StudyTask {
  const section = chapter.sections.find((item) => item.id === sectionId)
  return {
    id: `tutorial:${chapter.id}:${sectionId}`,
    kind: 'tutorial',
    title: `读「${section?.title ?? chapter.title}」`,
    est_min: tutorialMinutes(minutes),
    direction: chapter.direction,
    chapter_id: chapter.id,
    section_id: sectionId,
    href: tutorialHref(chapter.id, sectionId),
    reason,
    shortfall,
  }
}

function firstUnreadSection(
  chapter: TutorialChapter,
  learned: LearnProgressState | undefined,
): string | null {
  const seen = new Set(learned?.chapters[chapter.id]?.seen ?? [])
  const section = chapter.sections.find((item) => !seen.has(item.id))
  return section?.id ?? null
}

interface Candidate {
  item: WeaknessItem
  weight: number
  index: number
  tasks: StudyTask[]
}

function tasksForItem(
  item: WeaknessItem,
  minutes: PlanMinutes,
  learned: LearnProgressState | undefined,
): StudyTask[] {
  const difficulty = filterValue(item.difficulty)
  const essentiality = filterValue(item.essentiality)
  const parts = [item.direction]
  if (difficulty !== 'all') parts.push(labelOf(DIFFICULTY_LABEL, difficulty))
  if (essentiality !== 'all') parts.push(labelOf(ESSENTIALITY_LABEL, essentiality))
  const reason = `${parts.join(' · ')}｜${item.summary}`
  const tasks: StudyTask[] = []

  const chapter = pickChapter(item.direction, targetLevel(item), item.sub_direction)
  if (chapter !== null) {
    // 「先读基础章」只是难度递进的代理：目标章不是基础章、且该方向基础章一节都没读过时插一条。
    if (LEVEL_ORDER[chapter.level] > LEVEL_ORDER['基础']) {
      const base = chaptersInDirection(item.direction).find(
        (candidate) => candidate.level === '基础',
      )
      if (base !== undefined && seenCount(learned, base.id) === 0) {
        const sectionId = firstUnreadSection(base, learned)
        if (sectionId !== null) {
          tasks.push(
            tutorialTask(base, sectionId, minutes, `前置：先读该方向基础章「${base.title}」`, null),
          )
        }
      }
    }
    const sectionId = firstUnreadSection(chapter, learned)
    if (sectionId !== null) {
      tasks.push(tutorialTask(chapter, sectionId, minutes, reason, item.point))
    }
  }

  tasks.push({
    id: `practice:${item.direction}:${difficulty}:${essentiality}`,
    kind: 'practice',
    title: `专项练习 10 题`,
    est_min: practiceMinutes(minutes),
    direction: item.direction,
    chapter_id: null,
    section_id: null,
    // r50：短板已带二级方向时，练习直接落到同一子方向（服务端聚焦不足会自动补位）。
    href: practiceHref({
      direction: item.direction,
      sub_direction: item.sub_direction ?? '',
      difficulty,
      essentiality,
      limit: 10,
    }),
    reason,
    shortfall: item.point,
  })
  return tasks
}

function genericFillers(minutes: PlanMinutes): Omit<StudyTask, 'id'>[] {
  return [
    {
      kind: 'review',
      title: '回看诊断报告，挑一个短板写下具体改进动作',
      est_min: reviewMinutes(minutes),
      direction: null,
      chapter_id: null,
      section_id: null,
      href: '/report',
      reason: '通用建议',
      shortfall: null,
    },
    {
      kind: 'practice',
      title: '重做错题，答对一次即移出错题本',
      est_min: practiceMinutes(minutes),
      direction: null,
      chapter_id: null,
      section_id: null,
      href: practiceHref({ scope: 'wrong', limit: 0 }),
      reason: '通用建议',
      shortfall: null,
    },
    {
      kind: 'practice',
      title: '综合练习 10 题，保持做题手感',
      est_min: practiceMinutes(minutes),
      direction: null,
      chapter_id: null,
      section_id: null,
      href: practiceHref({ limit: 10 }),
      reason: '通用建议',
      shortfall: null,
    },
    {
      kind: 'practice',
      title: '去模拟笔试，按真实节奏做一套',
      est_min: minutes,
      direction: null,
      chapter_id: null,
      section_id: null,
      href: '/exam',
      reason: '通用建议',
      shortfall: null,
    },
    {
      kind: 'review',
      title: '去模拟面试，再对照报告看变化',
      est_min: minutes,
      direction: null,
      chapter_id: null,
      section_id: null,
      href: '/interview',
      reason: '通用建议',
      shortfall: null,
    },
  ]
}

/**
 * 生成 7 天计划。`weakness_map === null`（旧报告）或 `[]`（本次无计分题）返回空计划，
 * 由 `WeekPlan` 展示对应提示（与报告页既有口径一致）。
 */
export function buildStudyPlan(
  report: Report,
  options: { dailyMinutes: PlanMinutes; learned?: LearnProgressState },
): StudyPlan {
  const { dailyMinutes, learned } = options
  const empty: StudyPlan = {
    version: PLAN_VERSION,
    report_id: report.id,
    daily_minutes: dailyMinutes,
    days: [],
    truncated: false,
    updated_at: new Date().toISOString(),
  }
  if (report.weakness_map === null || report.weakness_map.length === 0) return empty

  const candidates: Candidate[] = report.weakness_map
    .map((item, index) => ({
      item,
      index,
      weight: weightOf(item),
      tasks: tasksForItem(item, dailyMinutes, learned),
    }))
    .sort((a, b) => b.weight - a.weight || a.index - b.index)

  // 去重：同一门课 / 同一小节被多条短板选中时只排一次（保留权重最高的那条）。
  const seenTaskIds = new Set<string>()
  const ordered: StudyTask[] = []
  for (const candidate of candidates) {
    for (const task of candidate.tasks) {
      if (seenTaskIds.has(task.id)) continue
      seenTaskIds.add(task.id)
      ordered.push(task)
    }
  }

  const days: StudyDay[] = Array.from({ length: PLAN_DAY_COUNT }, (_, index) => ({
    day: index + 1,
    minutes: 0,
    tasks: [],
  }))
  let dayIndex = 0
  let used = 0
  let truncated = false
  for (const task of ordered) {
    while (dayIndex < PLAN_DAY_COUNT && used + task.est_min > dailyMinutes) {
      dayIndex += 1
      used = 0
    }
    if (dayIndex >= PLAN_DAY_COUNT) {
      truncated = true
      break
    }
    days[dayIndex].tasks.push(task)
    used += task.est_min
    days[dayIndex].minutes = used
  }

  // 短板任务不足 7 天：用通用任务补空天（每天至少一条），绝不编造短板名。
  const fillers = genericFillers(dailyMinutes)
  let fillerIndex = 0
  for (let index = 0; index < PLAN_DAY_COUNT; index += 1) {
    const day = days[index]
    while (day.tasks.length === 0) {
      const filler = fillers[fillerIndex % fillers.length]
      day.tasks.push({
        ...filler,
        id: `review:${fillerIndex % fillers.length}:d${day.day}`,
      })
      day.minutes = filler.est_min
      fillerIndex += 1
    }
  }

  return {
    ...empty,
    days,
    truncated,
    updated_at: new Date().toISOString(),
  }
}

/** 计划进度：任务粒度（技术方案 B1：打卡按 task.id，不按天）。 */
export function planStats(
  plan: StudyPlan,
  done: Record<string, true>,
): { total: number; completed: number; doneDays: number; percent: number } {
  let total = 0
  let completed = 0
  let doneDays = 0
  for (const day of plan.days) {
    total += day.tasks.length
    const dayDone = day.tasks.filter((task) => done[task.id] === true).length
    completed += dayDone
    if (day.tasks.length > 0 && dayDone === day.tasks.length) doneDays += 1
  }
  return {
    total,
    completed,
    doneDays,
    percent: total === 0 ? 0 : Math.round((completed / total) * 100),
  }
}

export function isDayDone(day: StudyDay, done: Record<string, true>): boolean {
  return day.tasks.length > 0 && day.tasks.every((task) => done[task.id] === true)
}

function isPlanMinutes(value: unknown): value is PlanMinutes {
  return value === 15 || value === 30 || value === 60
}

export function planStorageKey(userId: string, reportId: string): string {
  return `sc.plan.${userId}.${reportId}`
}

export function planStateStorageKey(userId: string, reportId: string): string {
  return `sc.planState.${userId}.${reportId}`
}

/** 解析计划快照：版本 / 时长 / 结构任一不合法就整份丢弃（调用方重算）。 */
export function parseStoredPlan(raw: string | null): StudyPlan | null {
  if (raw === null) return null
  try {
    const parsed = JSON.parse(raw) as Partial<StudyPlan> | null
    if (
      parsed === null ||
      typeof parsed !== 'object' ||
      parsed.version !== PLAN_VERSION ||
      !isPlanMinutes(parsed.daily_minutes) ||
      !Array.isArray(parsed.days)
    ) {
      return null
    }
    return parsed as StudyPlan
  } catch {
    return null
  }
}

/** 解析打卡状态：坏数据退回 `null`（不炸页面，打卡只是本地体验数据）。 */
export function parsePlanState(raw: string | null): PlanState | null {
  if (raw === null) return null
  try {
    const parsed = JSON.parse(raw) as Partial<PlanState> | null
    if (
      parsed === null ||
      typeof parsed !== 'object' ||
      parsed.version !== PLAN_VERSION ||
      !isPlanMinutes(parsed.daily_minutes) ||
      parsed.done === null ||
      typeof parsed.done !== 'object'
    ) {
      return null
    }
    const done: Record<string, true> = {}
    for (const [key, value] of Object.entries(parsed.done as Record<string, unknown>)) {
      if (value === true) done[key] = true
    }
    return { version: PLAN_VERSION, daily_minutes: parsed.daily_minutes, done }
  } catch {
    return null
  }
}
