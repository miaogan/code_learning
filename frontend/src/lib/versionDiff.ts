import type { Profile, ResumeVersionDetail } from '../api/types'

/**
 * r60 简历版本对比的纯函数层（页面零计算）。
 *
 * 口径：
 * - 画像计数只数 **active** 项（`status='historical'` = 最新简历里已不出现，保留证据但不计入）；
 * - 成绩差只在**两端都有分**时给出（`null` 表示「该版本没有这一类有分记录」，不是 0 分）；
 * - `years_experience` 为 `null`（简历未写）时按 0 参与计数口径的对比，但页面同时显示原值「未填写」。
 */

export type MetricKey = 'skills' | 'tech_stack' | 'projects' | 'years' | 'chars' | 'sections'
export type ScoreKey = 'interview_avg' | 'exam_total' | 'judged_count'

export interface MetricDiff {
  key: MetricKey
  label: string
  before: number
  after: number
  /** `after - before`（正数=变多）。 */
  delta: number
}

export interface ScoreDiff {
  key: ScoreKey
  label: string
  before: number | null
  after: number | null
  /** 两端都有值时 `after - before`，否则 `null`（不能把「无记录」当成 0）。 */
  delta: number | null
  /** 满分口径（面试 10 / 笔试 100）；场数没有满分，为 `null`。 */
  scale: number | null
  unit: string
}

export interface VersionComparison {
  metrics: MetricDiff[]
  scores: ScoreDiff[]
  /** 画像侧是否有变化（含目标岗位、技术栈名单、能力项名单）。 */
  changed: boolean
  roleBefore: string | null
  roleAfter: string | null
  skillsAdded: string[]
  skillsRemoved: string[]
  techAdded: string[]
  techRemoved: string[]
}

function activeNames<T extends { name: string; status?: 'active' | 'historical' }>(items: T[]): string[] {
  return items.filter((item) => item.status !== 'historical').map((item) => item.name)
}

function addedRemoved(before: string[], after: string[]): [string[], string[]] {
  const beforeSet = new Set(before)
  const afterSet = new Set(after)
  return [
    after.filter((name) => !beforeSet.has(name)),
    before.filter((name) => !afterSet.has(name)),
  ]
}

function delta(before: number | null, after: number | null): number | null {
  if (before === null || after === null) return null
  return after - before
}

function profileOf(version: ResumeVersionDetail): Profile | null {
  return version.profile
}

export function compareVersions(
  before: ResumeVersionDetail,
  after: ResumeVersionDetail,
): VersionComparison {
  const beforeProfile = profileOf(before)
  const afterProfile = profileOf(after)
  const beforeSkills = activeNames(beforeProfile?.skills ?? [])
  const afterSkills = activeNames(afterProfile?.skills ?? [])
  const beforeTech = (beforeProfile?.tech_stack ?? []).filter(Boolean)
  const afterTech = (afterProfile?.tech_stack ?? []).filter(Boolean)
  const activeProjectCount = (profile: Profile | null): number =>
    (profile?.projects ?? []).filter((project) => project.status !== 'historical').length

  const metric = (key: MetricKey, label: string, a: number, b: number): MetricDiff => ({
    key,
    label,
    before: a,
    after: b,
    delta: b - a,
  })

  const metrics: MetricDiff[] = [
    metric('skills', '能力项', beforeSkills.length, afterSkills.length),
    metric('tech_stack', '技术栈', beforeTech.length, afterTech.length),
    metric('projects', '项目', activeProjectCount(beforeProfile), activeProjectCount(afterProfile)),
    metric(
      'years',
      '工作年限',
      beforeProfile?.years_experience ?? 0,
      afterProfile?.years_experience ?? 0,
    ),
    metric('chars', '正文字数', before.chars, after.chars),
    metric('sections', '识别分区', before.sections, after.sections),
  ]

  const scores: ScoreDiff[] = [
    {
      key: 'interview_avg',
      label: '面试均分',
      before: before.interview_avg,
      after: after.interview_avg,
      delta: delta(before.interview_avg, after.interview_avg),
      scale: 10,
      unit: '/10',
    },
    {
      key: 'exam_total',
      label: '笔试卷面',
      before: before.exam_total,
      after: after.exam_total,
      delta: delta(before.exam_total, after.exam_total),
      scale: 100,
      unit: '/100',
    },
    {
      key: 'judged_count',
      label: '已完成测评',
      before: before.judged_count,
      after: after.judged_count,
      delta: after.judged_count - before.judged_count,
      scale: null,
      unit: '场',
    },
  ]

  const [skillsAdded, skillsRemoved] = addedRemoved(beforeSkills, afterSkills)
  const [techAdded, techRemoved] = addedRemoved(beforeTech, afterTech)
  const roleBefore = beforeProfile?.target_role ?? null
  const roleAfter = afterProfile?.target_role ?? null
  const changed =
    metrics.some((item) => item.delta !== 0) ||
    skillsAdded.length > 0 ||
    skillsRemoved.length > 0 ||
    techAdded.length > 0 ||
    techRemoved.length > 0 ||
    roleBefore !== roleAfter

  return {
    metrics,
    scores,
    changed,
    roleBefore,
    roleAfter,
    skillsAdded,
    skillsRemoved,
    techAdded,
    techRemoved,
  }
}

/** 差值展示：`null` 显示 `—`，0 显示「持平」，否则带符号（数字用 Unicode 负号，避免与短横线混淆）。 */
export function formatDelta(value: number | null, digits = 1): string {
  if (value === null) return '—'
  if (value === 0) return '持平'
  return `${value > 0 ? '+' : '−'}${Math.abs(value).toFixed(digits)}`
}

/** 同一版本不能对比：页面据此给提示而不是画一条「全部持平」的假差异。 */
export function canCompare(before: ResumeVersionDetail, after: ResumeVersionDetail): boolean {
  return before.resume_id !== after.resume_id
}
