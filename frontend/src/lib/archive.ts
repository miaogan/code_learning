/**
 * r63 学习档案的纯函数层（页面零计算，导出与页面共用同一份口径）。
 *
 * 三条口径：
 * 1. 画像只数 **active** 项（`status='historical'` = 最新简历里已不出现，证据保留但不计入）；
 * 2. 成绩取自 `GET /api/history` 的倒序列表：同类「最近一次」= 该类型第一条**有分**记录，
 *    提前结束且一题未答的记录（`score=null`）会被跳过且**不补 0**（与 `history.score_of` 同源）；
 * 3. 全部读数都是「站内痕迹」，不含能力评级，也不代表求职结果 —— 页面与导出文件都明说这一点。
 */

import type { Profile, Report, ResumeVersionSummary, RunSummary } from '../api/types'
import { summarizeProgress, type LearnProgressState } from './learnProgress'
import { planStats, type PlanMinutes, type StudyPlan } from './studyPlan'
import { ALL_TUTORIAL_CHAPTERS } from './tutorials'
import { formatChars, formatScore, formatWhen } from './format'

/** 导出名前缀（与 `exportName` 同为「单一命名真源」，只是属于不同产物）。 */
export const ARCHIVE_PREFIX = '学习档案-'

/** 薄弱方向最多列出 5 条：档案是摘要，不是完整报告。 */
export const MAX_ARCHIVE_WEAKNESSES = 5

export interface ArchiveProfile {
  targetRole: string | null
  years: number | null
  skills: string[]
  tech: string[]
  projects: number
}

export interface ArchiveScores {
  interviewCount: number
  examCount: number
  judgedCount: number
  /** 最近一次**有分**的面试均分（0–10）；没有记录时为 `null`。 */
  latestInterview: number | null
  /** 最近一次**有分**的笔试卷面（0–100）；没有记录时为 `null`。 */
  latestExam: number | null
}

export interface ArchiveWeakness {
  direction: string
  subDirection: string
  wrong: number
  total: number
  rate: number
}

export interface ArchiveVersions {
  count: number
  latest: ResumeVersionSummary | null
}

export interface ArchiveLearn {
  done: number
  reading: number
  chapters: number
  percent: number
}

export interface ArchivePlan {
  total: number
  completed: number
  percent: number
}

export interface ArchiveSnapshot {
  profile: ArchiveProfile | null
  scores: ArchiveScores
  versions: ArchiveVersions
  weaknesses: ArchiveWeakness[]
  /** `null` = 还没有诊断报告；`[]` = 报告存在但本次无已计分题（与 `weakness_map` 同口径）。 */
  weaknessesAvailable: boolean
  reportAt: string | null
  learn: ArchiveLearn
  plan: ArchivePlan | null
}

export interface ArchiveInput {
  profile: Profile | null
  versions: ResumeVersionSummary[]
  /** `GET /api/history` 的原序（服务端倒序），本文件不再重排。 */
  runs: RunSummary[]
  report: Report | null
  progress: LearnProgressState
  /** `null` = 没有报告或不展示计划；有值时按 `planDone` 统计打卡。 */
  plan: StudyPlan | null
  planDone: Record<string, true>
}

function activeNames<T extends { name: string; status?: 'active' | 'historical' }>(
  items: T[],
): string[] {
  return items.filter((item) => item.status !== 'historical').map((item) => item.name)
}

function recentScore(runs: RunSummary[], kind: 'interview' | 'exam'): number | null {
  for (const run of runs) {
    if (run.kind !== kind) continue
    if (typeof run.score === 'number') return run.score
  }
  return null
}

/** 错误率降序 → 错题数降序 → 方向名（保证同一份报告复算顺序稳定）。 */
function sortWeaknesses(report: Report): ArchiveWeakness[] {
  const items = (report.weakness_map ?? []).filter((item) => item.total > 0)
  return items
    .map((item) => ({
      direction: item.direction,
      subDirection: item.sub_direction ?? '',
      wrong: item.wrong,
      total: item.total,
      rate: item.rate,
    }))
    .sort(
      (a, b) =>
        b.rate - a.rate ||
        b.wrong - a.wrong ||
        a.direction.localeCompare(b.direction) ||
        a.subDirection.localeCompare(b.subDirection),
    )
    .slice(0, MAX_ARCHIVE_WEAKNESSES)
}

export function buildArchiveSnapshot(input: ArchiveInput): ArchiveSnapshot {
  const { profile, versions, runs, report, progress, plan, planDone } = input

  const skillNames = activeNames(profile?.skills ?? [])
  const techNames = (profile?.tech_stack ?? []).filter(Boolean)
  const projectCount = (profile?.projects ?? []).filter(
    (project) => project.status !== 'historical',
  ).length
  const summary = summarizeProgress(progress, ALL_TUTORIAL_CHAPTERS)
  const stats = plan === null ? null : planStats(plan, planDone)

  return {
    profile:
      profile === null
        ? null
        : {
            targetRole: profile.target_role ?? null,
            years: profile.years_experience ?? null,
            skills: skillNames,
            tech: techNames,
            projects: projectCount,
          },
    scores: {
      interviewCount: runs.filter((run) => run.kind === 'interview').length,
      examCount: runs.filter((run) => run.kind === 'exam').length,
      judgedCount: runs.filter((run) => typeof run.score === 'number').length,
      latestInterview: recentScore(runs, 'interview'),
      latestExam: recentScore(runs, 'exam'),
    },
    versions: {
      count: versions.length,
      latest: versions[0] ?? null,
    },
    weaknesses: report === null ? [] : sortWeaknesses(report),
    weaknessesAvailable: report !== null && report.weakness_map !== null,
    reportAt: report?.generated_at ?? null,
    learn: {
      done: summary.done,
      reading: summary.reading,
      chapters: summary.chapters,
      percent: summary.percent,
    },
    plan:
      stats === null
        ? null
        : { total: stats.total, completed: stats.completed, percent: stats.percent },
  }
}

function examScoreText(value: number | null): string {
  if (value === null) return '暂无记录'
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function weaknessLine(item: ArchiveWeakness, index: number): string {
  const scope = item.subDirection === '' ? item.direction : `${item.direction} · ${item.subDirection}`
  return `${index + 1}. ${scope}：错 ${item.wrong} / ${item.total} 题，错误率 ${Math.round(item.rate * 100)}%`
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** 本地时间戳（导出文件里写给「什么时候导的」，不参与任何计算）。 */
function stamp(now: Date): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(
    now.getHours(),
  )}:${pad(now.getMinutes())}`
}

/**
 * 学习档案 Markdown：与页面内容同源（同一份 `ArchiveSnapshot`），页面不再二次拼串。
 * 空数据一律给「为什么空 + 怎么补」的中文说明，不写「暂无数据」。
 */
export function archiveMarkdown(snapshot: ArchiveSnapshot, now: Date = new Date()): string {
  const { profile, scores, versions, weaknesses, learn, plan } = snapshot
  const lines: string[] = []

  lines.push('# 学习档案', '')
  lines.push(`生成时间：${stamp(now)}`, '')
  lines.push(
    '> 本档案由「逃跑计划」站内记录汇总，只反映你在本站的测评与学习痕迹，不代表能力评级或求职结果。',
    '',
  )

  lines.push('## 目标与画像', '')
  if (profile === null) {
    lines.push('还没有技术画像：上传简历并生成画像后，这里会给出证据盘点的摘要。')
  } else {
    lines.push(`- 目标岗位：${profile.targetRole ?? '未填写'}`)
    lines.push(`- 工作年限：${profile.years === null ? '未填写' : `${profile.years} 年`}`)
    lines.push(
      profile.skills.length === 0
        ? '- 能力项：暂无'
        : `- 能力项（${profile.skills.length}）：${profile.skills.join('、')}`,
    )
    lines.push(
      profile.tech.length === 0
        ? '- 技术栈：暂无'
        : `- 技术栈（${profile.tech.length}）：${profile.tech.join('、')}`,
    )
    lines.push(`- 项目：${profile.projects} 个`)
  }
  lines.push('')

  lines.push('## 测评成绩', '')
  if (scores.judgedCount === 0) {
    lines.push('还没有已计分的测评记录：完成一场模拟面试或模拟笔试后会出现在这里。')
  } else {
    lines.push(`- 已完成计分测评 ${scores.judgedCount} 场（面试 ${scores.interviewCount} / 笔试 ${scores.examCount}）`)
    lines.push(
      `- 面试最近一次：${
        scores.latestInterview === null ? '暂无记录' : `${formatScore(scores.latestInterview)} / 10`
      }`,
    )
    lines.push(`- 笔试最近一次：${examScoreText(scores.latestExam)} / 100`)
  }
  lines.push('')

  lines.push('## 简历版本', '')
  if (versions.latest === null) {
    lines.push('还没有简历版本：上传第一份简历即开始存档。')
  } else {
    const latest = versions.latest
    lines.push(
      `- 共 ${versions.count} 个版本，最新 ${formatWhen(latest.created_at)} · ${latest.file_name}` +
        `（${formatChars(latest.chars)} · ${latest.sections} 个分区）`,
    )
  }
  lines.push('')

  lines.push(`## 薄弱方向（按错误率取前 ${MAX_ARCHIVE_WEAKNESSES}）`, '')
  if (!snapshot.weaknessesAvailable) {
    lines.push('还没有诊断报告：完成一次有计分的测评并生成报告后，薄弱方向才会出现在档案里。')
  } else if (weaknesses.length === 0) {
    lines.push('本次报告里没有形成薄弱方向（没有可计分的客观题）。')
  } else {
    weaknesses.forEach((item, index) => lines.push(weaknessLine(item, index)))
  }
  lines.push('')

  lines.push('## 学习进度', '')
  lines.push(`- 已读完 ${learn.done} 章，读到一半 ${learn.reading} 章，共 ${learn.chapters} 章`)
  lines.push(`- 小节进度：${learn.percent}%（按已读小节加权，只记「读过」不记「掌握」）`)
  lines.push('')

  lines.push('## 7 天计划', '')
  if (plan === null) {
    lines.push('还没有可用的 7 天计划：生成诊断报告后，报告页会按短板排出计划。')
  } else if (plan.total === 0) {
    lines.push('本次报告的短板没有可排入计划的条目。')
  } else {
    lines.push(`- 已完成 ${plan.completed} / ${plan.total} 个任务（${plan.percent}%）`)
    lines.push('- 打卡只记「做完」，不计入熟练度或成绩。')
  }
  lines.push('')

  return `${lines.join('\n')}\n`
}

/** 导出文件名：`学习档案-<yyyy-mm-dd>.md`（同一天多次导出同名，由浏览器自动加序号）。 */
export function archiveFileName(now: Date = new Date()): string {
  return `${ARCHIVE_PREFIX}${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}.md`
}

/** 完全没有任何记录时的判定：页面给空态，而不是画一张全「暂无」的表。 */
export function isEmptyArchive(snapshot: ArchiveSnapshot): boolean {
  return (
    snapshot.profile === null &&
    snapshot.scores.judgedCount === 0 &&
    snapshot.versions.count === 0 &&
    snapshot.weaknessesAvailable === false
  )
}

/** 计划每日时长兜底：沿用报告页默认 30 分钟（`PLAN_MINUTES` 的中间档）。 */
export const DEFAULT_ARCHIVE_MINUTES: PlanMinutes = 30
