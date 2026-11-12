/**
 * 报告 → 7 天可执行学习计划（r41 功能 B，B1 纯前端确定性排程）。
 *
 * 输入只有三份真实数据：报告里的薄弱地图、站内教程目录、本地已读小节；
 * 输出是可单测、可重算的固定 7 天任务表。**不调接口、不调 AI、不计入任何成绩**。
 *
 * 三条不能破的口径：
 * 1. 任务只能指回站内真实入口（教程章节 / 小节、练习筛选、科考召对）；
 * 2. 短板不足时用通用任务补位，**绝不编造短板名**；
 * 3. 教程章有「方向 / 子方向 / 难度」但没有显式前置字段 —— 「先读基础章」是**难度递进代理**，
 *    UI 文案不得宣称那是真实课程依赖；短板带子方向时优先选同子方向章，挑不到静默回落方向级。
 */
import type { Report, WeaknessItem } from '../api/types'
import type { LearnProgressState } from './learnProgress'
import type { TutorialChapter, TutorialLevel } from './tutorialTypes'
import { ALL_TUTORIAL_CHAPTERS, chaptersInDirection } from './tutorials'
import { searchTutorials } from './tutorialSearch'
import { DIFFICULTY_LABEL, ESSENTIALITY_LABEL } from './practice'

export const PLAN_DAY_COUNT = 7
/** r51 刻意不 bump：citations 是纯附加可选字段，旧快照缺该字段时渲染零占位，无需失效重算。 */
export const PLAN_VERSION = 1 as const

/** 每日可用时长（分钟）：三档闭集，与 UI 选择器、存储校验共用一处。 */
export type PlanMinutes = 15 | 30 | 60
export const PLAN_MINUTES: PlanMinutes[] = [15, 30, 60]

export type TaskKind = 'tutorial' | 'practice' | 'review'

/** r51 检索增强：一条可点击的「为什么推这一章」引用（章 + 小节锚点）。 */
export interface PlanCitation {
  chapter_id: string
  section_id: string
  title: string
  href: string
  score: number
}

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
  /** r51：可选检索引用；旧快照 / 未开启检索时无此字段，渲染零占位。 */
  citations?: PlanCitation[]
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
  /** r95 计划起始日（本机日历日 `YYYY-MM-DD`）；空串 = 还没开始计时。 */
  started_on: string
}

export const PLAN_LEGACY_NOTICE = '旧报告不含薄弱地图，重新生成后可生成按短板排的学习计划'
export const PLAN_EMPTY_NOTICE = '本次测评还没有可排入计划的短板，完成一轮有计分的测评后再来'
/** 必须在界面上明说：打卡只记「做完」，不进评分；r61 起随账号同步（本地只是缓存）。 */
export const PLAN_SYNCED_NOTICE =
  '计划、起始日与打卡都保存在账号下：换设备登录同一账号可以接着打卡。打卡只记「做完」，不计入熟练度或成绩。'
/** r95：计划还没和日历对齐时的说明（Day 1 = 开始那天）。 */
export const PLAN_IDLE_NOTICE =
  '计划还没开始计时：点「今天开始」，Day 1 就是今天，之后每天对应一天。'
/** r95：7 天窗口走完但还有任务没做完。 */
export const PLAN_EXPIRED_NOTICE = '7 天已经过完，还剩没做完的任务：可以从今天重新排。'

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
  /** 单值或多选（多选按重复键写，练习页解析两种都吃）；`all` / 空数组 = 不写参数。 */
  direction?: string | readonly string[] | null
  /** r50：二级方向聚焦；空串 / null = 不聚焦，URL 用 `sub`（与学习目录页同参数名）。 */
  sub_direction?: string | null
  difficulty?: string | null
  essentiality?: string | null
  scope?: string | null
  limit?: number | null
}): string {
  const query = new URLSearchParams()
  const directions =
    typeof params.direction === 'string' ? [params.direction] : params.direction ?? []
  directions
    .filter((direction) => direction !== 'all')
    .forEach((direction) => query.append('direction', direction))
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

/** r51：检索「短板描述 → 教程小节」的依据。命中空集时静默不挂字段，绝不编造引用。 */
function citationsFor(item: WeaknessItem, chapterId: string): PlanCitation[] {
  const hits = searchTutorials(
    `${item.point} ${item.summary}`,
    { direction: item.direction, sub_direction: item.sub_direction ?? '' },
    ALL_TUTORIAL_CHAPTERS,
    3,
  )
  const scoped = hits.filter((hit) => hit.chapter_id === chapterId)
  const chosen = scoped.length > 0 ? scoped : hits.slice(0, 2)
  return chosen.map((hit) => ({
    chapter_id: hit.chapter_id,
    section_id: hit.section_id,
    title: hit.title,
    href: hit.href,
    score: hit.score,
  }))
}

function tasksForItem(
  item: WeaknessItem,
  minutes: PlanMinutes,
  learned: LearnProgressState | undefined,
  withCitations: boolean,
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
      const task = tutorialTask(chapter, sectionId, minutes, reason, item.point)
      if (withCitations) {
        const citations = citationsFor(item, chapter.id)
        if (citations.length > 0) task.citations = citations
      }
      tasks.push(task)
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
      title: '回看医案，挑一个短板写下具体改进动作',
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
      title: '去科考，按真实节奏做一套',
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
      title: '去召对，再对照报告看变化',
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
  options: { dailyMinutes: PlanMinutes; learned?: LearnProgressState; citations?: boolean },
): StudyPlan {
  const { dailyMinutes, learned, citations = false } = options
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
      tasks: tasksForItem(item, dailyMinutes, learned, citations),
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

/* ---------- r95 计划按日历推进：起始日 ↔ 今天 ---------- */

const DAY_MS = 86_400_000
const ISO_DAY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/

/** 本机日历日 `YYYY-MM-DD`。`toISOString()` 是 UTC，东八区凌晨会差一天，不能直接用。 */
export function isoDay(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function dayMsOf(iso: string): number | null {
  const match = ISO_DAY_PATTERN.exec(iso.trim())
  if (match === null) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const ms = Date.UTC(year, month - 1, day)
  const read = new Date(ms)
  // `2026-02-31` 形态合法但日历不成立，Date 会进位到 3 月；回读不一致即判坏值。
  if (
    read.getUTCFullYear() !== year ||
    read.getUTCMonth() !== month - 1 ||
    read.getUTCDate() !== day
  ) {
    return null
  }
  return ms
}

/** 是不是一个真实存在的日历日（`YYYY-MM-DD`）。 */
export function isPlanDay(value: string): boolean {
  return dayMsOf(value) !== null
}

/** `from` → `to` 的整天差（正数＝`to` 更晚）；任一侧不可解返回 `null`。 */
export function dayOffset(from: string, to: string): number | null {
  const a = dayMsOf(from)
  const b = dayMsOf(to)
  if (a === null || b === null) return null
  return Math.round((b - a) / DAY_MS)
}

/** 某个日历日挪 `days` 天（负数往前），返回 `YYYY-MM-DD`；不可解返回 `null`。 */
export function shiftDay(iso: string, days: number): string | null {
  const ms = dayMsOf(iso)
  if (ms === null) return null
  const shifted = new Date(ms + days * DAY_MS)
  const month = `${shifted.getUTCMonth() + 1}`.padStart(2, '0')
  const day = `${shifted.getUTCDate()}`.padStart(2, '0')
  return `${shifted.getUTCFullYear()}-${month}-${day}`
}

/** 计划与日历的对齐关系：今天对应哪天、落下了几天、第一个还没做完的是哪天。 */
export interface PlanPace {
  /** 起始日可解＝已经开始计时。 */
  started: boolean
  /** 起始日到今天的整天差（时钟回拨可能为负，页面按第 1 天处理）。 */
  offset: number | null
  /** 今天对应的 Day（1–7）；未开始或 7 天已过完为 `null`。 */
  todayDay: number | null
  /** 7 天窗口已经走完（`offset ≥ 7`）：今天不再属于这份计划。 */
  expired: boolean
  /** 今天之前还没做完的天数（不含今天本身）；未开始恒 0。 */
  behindDays: number
  /** 第一个还有未完成任务的 Day（1–7）；全部做完为 `null`。 */
  firstOpenDay: number | null
}

/**
 * 「今天该做哪天」的单一判定口。
 *
 * 三种状态刻意互斥：未开始（没有任何日期锚点）/ 进行中（`todayDay` 有值）/ 已过期
 * （7 天走完）。过期后不再假装「今天还是第 7 天」——那样用户会永远看到一个假的今天。
 */
export function planPace(
  plan: StudyPlan,
  done: Record<string, true>,
  startedOn: string,
  today: string,
): PlanPace {
  const offset = startedOn === '' ? null : dayOffset(startedOn, today)
  const started = offset !== null
  const elapsed = offset === null ? null : Math.max(0, offset)
  const expired = elapsed !== null && elapsed >= PLAN_DAY_COUNT
  const todayDay =
    elapsed === null || elapsed >= PLAN_DAY_COUNT ? null : elapsed + 1
  // 未开始不算「落后」（还没承诺哪天做）；今天本身不算落后（今天还有时间）；
  // 过期后 7 天全部算过去。
  const reach = !started
    ? 0
    : expired
      ? PLAN_DAY_COUNT
      : Math.max(0, (todayDay ?? 1) - 1)
  let firstOpenDay: number | null = null
  let behindDays = 0
  for (const day of plan.days) {
    if (isDayDone(day, done)) continue
    if (firstOpenDay === null) firstOpenDay = day.day
    if (day.day <= reach) behindDays += 1
  }
  return { started, offset, todayDay, expired, behindDays, firstOpenDay }
}

/** 「顺延」：把第一个没完成的那天挪到今天（前面已完成的进度不动）。 */
export function resumeDay(firstOpenDay: number, today: string): string | null {
  if (firstOpenDay < 1) return null
  return shiftDay(today, -(firstOpenDay - 1))
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

/* ---------- r61 打卡上云：本地状态 ↔ 服务端副本的映射与合并 ---------- */

/** 服务端返回的打卡状态；`updated_at` 为空串表示这份报告还没有任何云端记录。 */
export interface RemotePlanState {
  daily_minutes: PlanMinutes
  done: Record<string, boolean>
  /** r95：旧记录 / 老服务端没有该字段，按「未开始」处理。 */
  started_on?: string
  updated_at?: string
}

/** 上推载荷：只带「已打卡」条目，取消打卡等价于不在 map 里（服务端同样只存 `true`）。 */
export function planPushPayload(state: PlanState): {
  daily_minutes: PlanMinutes
  done: Record<string, boolean>
  started_on: string
} {
  const done: Record<string, boolean> = {}
  for (const [taskId, flag] of Object.entries(state.done)) {
    if (flag) done[taskId] = true
  }
  return {
    daily_minutes: state.daily_minutes,
    done,
    started_on: isPlanDay(state.started_on) ? state.started_on : '',
  }
}

/**
 * 云端优先、打卡取并集：云端已有记录时时长与起始日以云端为准（跨设备改过的偏好不能被本机旧值覆盖），
 * 打卡保留两侧的 `true`（打卡是单调的，不存在「云端取消本机打卡」这种语义）。
 *
 * 起始日另有一条口子：云端记录存在但起始日为空（旧版本写的打卡 / 本机离线时才开始），
 * 此时保留本机起始日——否则本机刚点的「今天开始」会被一次旧云端记录抹成未开始。
 */
export function mergePlanState(local: PlanState, remote: RemotePlanState): PlanState {
  const hasRemote = (remote.updated_at ?? '') !== ''
  const minutes = hasRemote && PLAN_MINUTES.includes(remote.daily_minutes)
    ? remote.daily_minutes
    : local.daily_minutes
  const done: Record<string, true> = { ...local.done }
  for (const [taskId, flag] of Object.entries(remote.done)) {
    if (flag === true) done[taskId] = true
  }
  const remoteStart = remote.started_on ?? ''
  const started_on = isPlanDay(remoteStart)
    ? remoteStart
    : isPlanDay(local.started_on)
      ? local.started_on
      : ''
  return { ...local, daily_minutes: minutes, done, started_on }
}

/** 两次打卡状态是否等价（`done` 只比较键集合，不比较 `false` 残留）。 */
export function samePlanState(a: RemotePlanState, b: RemotePlanState): boolean {
  if (a.daily_minutes !== b.daily_minutes) return false
  if ((a.started_on ?? '') !== (b.started_on ?? '')) return false
  const keysA = Object.keys(a.done).filter((taskId) => a.done[taskId])
  const keysB = Object.keys(b.done).filter((taskId) => b.done[taskId])
  if (keysA.length !== keysB.length) return false
  return keysA.every((taskId) => b.done[taskId] === true)
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
    const startedOn = typeof parsed.started_on === 'string' ? parsed.started_on : ''
    return {
      version: PLAN_VERSION,
      daily_minutes: parsed.daily_minutes,
      done,
      started_on: isPlanDay(startedOn) ? startedOn : '',
    }
  } catch {
    return null
  }
}
