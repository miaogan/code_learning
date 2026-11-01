import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type {
  Evidence,
  Profile,
  ProfileMergeSummary,
  ProfilePatch,
  ProfileProject,
  ProfileSkill,
} from '../api/types'
import { EvidenceList } from '../components/profile/EvidenceList'
import { MergeSummaryBar } from '../components/profile/MergeSummaryBar'
import { ProfileDimension } from '../components/profile/ProfileDimension'
import type { DimensionEntry, ProfileDimensionKey } from '../components/profile/ProfileDimension'
import { ProfileEditor } from '../components/profile/ProfileEditor'
import type { EditorField } from '../components/profile/ProfileEditor'
import { Chip } from '../components/ui/Chip'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { useAsync } from '../lib/useAsync'


/* #region t8-logic */
/** 5 维度的展示顺序与文案（DESIGN §2.2）；顺序即页面自上而下的卡序。 */
export const DIMENSIONS: ReadonlyArray<{
  key: ProfileDimensionKey
  title: string
  hint: string
  /** 单值维度才给整维编辑入口（列表维度按条目编辑）。 */
  editable: boolean
}> = [
  { key: 'skills', title: '技能标签', hint: '还没从简历里解析出技能标签', editable: false },
  { key: 'tech_stack', title: '技术栈', hint: '还没从简历里解析出技术栈', editable: true },
  { key: 'years_experience', title: '工作年限', hint: '简历里没有写工作年限，可手动补充', editable: true },
  { key: 'projects', title: '项目经历', hint: '还没从简历里解析出项目经历', editable: false },
  { key: 'target_role', title: '目标岗位', hint: '简历里没有写目标岗位，可手动补充', editable: true },
]

/** 条目 key = `维度#序号`：编辑/删除都只带这串，页面无需缓存整棵画像树。 */
export function entryKeyOf(dimension: ProfileDimensionKey, index: number): string {
  return `${dimension}#${index}`
}

export function parseEntryKey(entryKey: string): { dimension: ProfileDimensionKey; index: number } | null {
  const separator = entryKey.indexOf('#')
  if (separator <= 0) return null
  const dimension = entryKey.slice(0, separator) as ProfileDimensionKey
  const rawIndex = entryKey.slice(separator + 1)
  if (rawIndex.trim() === '') return null
  const index = Number(rawIndex)
  if (!Number.isInteger(index) || index < 0) return null
  const known = DIMENSIONS.some((item) => item.key === dimension)
  if (!known) return null
  return { dimension, index }
}

/** 带累积证据的条目（技能与项目共用同一判定口径；`source_quotes`/`status` 为 r3 新增字段）。 */
type TrackedEntry = {
  name: string
  source_quote: string
  source_quotes?: Evidence[]
  status?: string
}

/** 兼容回填口径（PRD R1）：`source_quotes` 为空 ⇒ 用兼容字段 `source_quote` 组成首条证据。 */
export function evidenceOf(entry: TrackedEntry): Evidence[] {
  const quotes = entry.source_quotes
  if (Array.isArray(quotes) && quotes.length > 0) return quotes
  const compat = typeof entry.source_quote === 'string' ? entry.source_quote.trim() : ''
  return compat === '' ? [] : [{ quote: entry.source_quote, resume_id: '', file_name: '', captured_at: '' }]
}

/** 消失项（本次简历未出现）由服务端标 `historical`：证据保留，但不进主卡片、不进策划素材。 */
export function isHistorical(entry: TrackedEntry): boolean {
  return entry.status === 'historical'
}

/** 历史能力 / 历史项目（折叠分组的数据源：页面只分组，不重算合并结果）。 */
export function historicalSkills(profile: Profile): ProfileSkill[] {
  return profile.skills.filter((item) => isHistorical(item))
}

export function historicalProjects(profile: Profile): ProfileProject[] {
  return profile.projects.filter((item) => isHistorical(item))
}

/**
 * 历史分组容器的 DOM id（r4 D-4）：`MergeSummaryBar` 按钮的 `aria-controls` 与容器 `id`
 * **必须来自同一常量**，页面里不各写一遍，避免两处字符串漂移（AC-11）。
 */
export const HISTORY_GROUP_ID = {
  skills: 'profile-history-skills',
  projects: 'profile-history-projects',
} as const

/** 一次性合并摘要的入参校验：`location.state` 属不可信外部输入，字段不合法就整条不渲染。 */
export function normalizeMergeSummary(raw: unknown): ProfileMergeSummary | null {
  if (typeof raw !== 'object' || raw === null) return null
  const record = raw as Record<string, unknown>
  const added = record.added
  const historical = record.historical
  const evidenceAdded = record.evidence_added
  if (typeof added !== 'number' || !Number.isFinite(added) || added < 0) return null
  if (typeof historical !== 'number' || !Number.isFinite(historical) || historical < 0) return null
  if (typeof evidenceAdded !== 'number' || !Number.isFinite(evidenceAdded) || evidenceAdded < 0) return null
  return { added, historical, evidence_added: evidenceAdded, duplicate: record.duplicate === true }
}

/** 从 `navigate('/profile', { state: { merge } })` 的 state 取出摘要（缺失/脏 payload ⇒ null）。 */
export function readMergeSummary(state: unknown): ProfileMergeSummary | null {
  if (typeof state !== 'object' || state === null) return null
  return normalizeMergeSummary((state as { merge?: unknown }).merge)
}

/** 画像 → 5 维度条目（纯函数，无副作用；页面与检查脚本共用同一份映射）。 */
export function dimensionEntries(profile: Profile): Record<ProfileDimensionKey, DimensionEntry[]> {
  return {
    skills: profile.skills.flatMap((item, index) =>
      isHistorical(item)
        ? []
        : [
            {
              key: entryKeyOf('skills', index),
              title: item.name,
              // 兼容字段为空但已有累积证据时回落到首条证据，避免误报「缺失来源」。
              sourceQuote: evidenceOf(item)[0]?.quote ?? item.source_quote,
            },
          ],
    ),
    tech_stack: profile.tech_stack.map((item, index) => ({
      key: entryKeyOf('tech_stack', index),
      title: item,
    })),
    projects: profile.projects.flatMap((item, index) =>
      isHistorical(item)
        ? []
        : [
            {
              key: entryKeyOf('projects', index),
              title: item.name,
              meta: [item.role, item.period].filter((part) => part.trim() !== '').join(' · '),
              bullets: item.bullets,
              // 同上：累积证据优先，兼容字段兜底。
              sourceQuote: evidenceOf(item)[0]?.quote ?? item.source_quote,
            },
          ],
    ),
    years_experience: [],
    target_role: [],
  }
}

/** 单值维度的展示值；null ⇒ 未填写（页面显示 emptyHint 而不是空白）。 */
export function singleValueOf(profile: Profile, dimension: ProfileDimensionKey): string | null {
  if (dimension === 'years_experience') {
    const years = profile.years_experience
    return years === null || years === undefined ? null : `${years} 年`
  }
  if (dimension === 'target_role') {
    const role = profile.target_role
    return typeof role === 'string' && role.trim() !== '' ? role : null
  }
  return null
}

/** 有内容的维度数（DESIGN 侧栏「5/5 维度已确认」）。 */
export function confirmedDimensions(profile: Profile): number {
  return DIMENSIONS.filter((item) => {
    if (item.key === 'years_experience') return profile.years_experience !== null && profile.years_experience !== undefined
    if (item.key === 'target_role') return profile.target_role !== null && profile.target_role.trim() !== ''
    return (dimensionEntries(profile)[item.key] ?? []).length > 0
  }).length
}

/** 带溯源片段的条目数（页头摘要行 + 侧栏）：按**证据条数**统计（旧→新累积后一条能力可有多条来源）。 */
export function sourceCount(profile: Profile): number {
  const active = [...profile.skills, ...profile.projects].filter((item) => !isHistorical(item))
  return active.reduce((total, item) => total + evidenceOf(item).length, 0)
}

/** 逗号 / 顿号 / 分号 / 换行都当分隔符（技术栈这类自由输入用）。 */
export function splitList(raw: string | undefined): string[] {
  if (raw === undefined) return []
  return raw
    .split(/[,，、;；\n]/)
    .map((item) => item.trim())
    .filter((item) => item !== '')
}

function trimToNull(raw: string | undefined): string | null {
  if (raw === undefined) return null
  const trimmed = raw.trim()
  return trimmed === '' ? null : trimmed
}

/** 年限：空 ⇒ null；非数字（编辑器已挡掉）⇒ null。 */
export function parseYears(raw: string | undefined): number | null {
  if (raw === undefined) return null
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

/** 删除一条条目：整维数组替换（PATCH 语义是「给什么就整列换成什么」）。 */
export function buildDeletePatch(
  profile: Profile,
  dimension: ProfileDimensionKey,
  index: number,
): ProfilePatch | null {
  if (dimension === 'skills') {
    if (index < 0 || index >= profile.skills.length) return null
    return { skills: profile.skills.filter((_, slot) => slot !== index) }
  }
  if (dimension === 'projects') {
    if (index < 0 || index >= profile.projects.length) return null
    return { projects: profile.projects.filter((_, slot) => slot !== index) }
  }
  if (dimension === 'tech_stack') {
    if (index < 0 || index >= profile.tech_stack.length) return null
    return { tech_stack: profile.tech_stack.filter((_, slot) => slot !== index) }
  }
  return null
}

/**
 * 编辑兼容字段 `source_quote` 时**同步首条证据**，保持 `source_quote == source_quotes[0].quote`（单源口径）；
 * 其余证据（更早的来源）原样保留、`status` 也不动 —— PATCH 必须「展开原条目」，否则一次编辑就会把
 * `source_quotes`/`status`（AC-6/AC-7 的累积与历史语义）整段丢掉。
 */
function quoteFields(entry: TrackedEntry, values: Record<string, string>): {
  source_quote: string
  source_quotes?: Evidence[]
} {
  const quote = (values.source_quote ?? entry.source_quote).trim()
  const quotes = entry.source_quotes
  if (!Array.isArray(quotes) || quotes.length === 0) {
    return { source_quote: quote }
  }
  return { source_quote: quote, source_quotes: [{ ...quotes[0], quote }, ...quotes.slice(1)] }
}

/** 编辑一条条目：只回传被改的那一维，其余维度不动（避免整画像覆盖）。 */
export function buildEntryPatch(
  profile: Profile,
  dimension: ProfileDimensionKey,
  index: number,
  values: Record<string, string>,
): ProfilePatch | null {
  if (dimension === 'skills') {
    const target = profile.skills[index]
    if (!target) return null
    const items = profile.skills.slice()
    items[index] = {
      ...target,
      ...quoteFields(target, values),
      name: (values.name ?? target.name).trim(),
    }
    return { skills: items }
  }
  if (dimension === 'projects') {
    const target = profile.projects[index]
    if (!target) return null
    const items = profile.projects.slice()
    items[index] = {
      ...target,
      ...quoteFields(target, values),
      name: (values.name ?? target.name).trim(),
      role: (values.role ?? target.role).trim(),
      period: (values.period ?? target.period).trim(),
      bullets: values.bullets === undefined ? target.bullets : splitList(values.bullets),
    }
    return { projects: items }
  }
  return null
}

/** 整维编辑（技术栈 / 年限 / 目标岗位）。 */
export function buildDimensionPatch(
  _profile: Profile,
  dimension: ProfileDimensionKey,
  values: Record<string, string>,
): ProfilePatch | null {
  if (dimension === 'tech_stack') return { tech_stack: splitList(values.tech_stack) }
  if (dimension === 'years_experience') return { years_experience: parseYears(values.years_experience) }
  if (dimension === 'target_role') return { target_role: trimToNull(values.target_role) }
  return null
}

/** 条目的编辑字段（技能 2 项、项目 5 项）。 */
export function entryEditorFields(
  profile: Profile,
  dimension: ProfileDimensionKey,
  index: number,
): EditorField[] {
  if (dimension === 'skills') {
    const target = profile.skills[index]
    if (!target) return []
    return [
      { key: 'name', label: '技能名称', kind: 'text', value: target.name },
      { key: 'source_quote', label: '简历原文（溯源）', kind: 'textarea', value: target.source_quote },
    ]
  }
  if (dimension === 'projects') {
    const target = profile.projects[index]
    if (!target) return []
    return [
      { key: 'name', label: '项目名称', kind: 'text', value: target.name },
      { key: 'role', label: '角色', kind: 'text', value: target.role },
      { key: 'period', label: '时间', kind: 'text', value: target.period },
      {
        key: 'bullets',
        label: '项目要点（每行一条）',
        kind: 'textarea',
        value: target.bullets.join('\n'),
      },
      { key: 'source_quote', label: '简历原文（溯源）', kind: 'textarea', value: target.source_quote },
    ]
  }
  return []
}

/** 整维的编辑字段（技术栈一行一个、年限数字、目标岗位单行）。 */
export function dimensionEditorFields(
  profile: Profile,
  dimension: ProfileDimensionKey,
): EditorField[] {
  if (dimension === 'tech_stack') {
    return [
      {
        key: 'tech_stack',
        label: '技术栈（逗号或换行分隔）',
        kind: 'textarea',
        value: profile.tech_stack.join('、'),
        placeholder: '例如：TypeScript、React、FastAPI',
      },
    ]
  }
  if (dimension === 'years_experience') {
    return [
      {
        key: 'years_experience',
        label: '工作年限',
        kind: 'number',
        value:
          profile.years_experience === null || profile.years_experience === undefined
            ? ''
            : String(profile.years_experience),
        placeholder: '例如：3',
      },
    ]
  }
  if (dimension === 'target_role') {
    return [
      { key: 'target_role', label: '目标岗位', kind: 'text', value: profile.target_role ?? '' },
    ]
  }
  return []
}

/**
 * PATCH 的落地规则（AC-2「逐条编辑」的确定性部分）：**成功才替换**，失败保持原值。
 * 写成纯函数是为了让「保存失败不丢数据、不假乐观更新」可被机器复算。
 */
export type PatchOutcome = { ok: true; profile: Profile } | { ok: false; message: string }

export function nextProfile(current: Profile, outcome: PatchOutcome): Profile {
  return outcome.ok ? outcome.profile : current
}

/**
 * 长简历截断提示。
 * 后端把超长正文截到 12000 字后才送模型（services/profile.py 的 MAX_PROFILE_CHARS），
 * 但 **当前契约没有把「是否截断」回传给前端**：`Profile` 只有 resume_id，也没有 `GET /api/resumes/{id}`。
 * 因此这里按可选字段诚实探测：字段不存在 ⇒ 不提示（绝不无脑常亮一个不成立的提示）；
 * 后端补齐 `truncated`（并与 `api/types.ts` 同步）后本提示自动生效。
 */
export function resumeTruncationNote(profile: Profile | null): string | null {
  if (profile === null) return null
  const probe = profile as Profile & { truncated?: boolean }
  return probe.truncated === true
    ? '长简历已截取前 12000 字：超出部分没有进入画像，可重新上传更精简的版本。'
    : null
}
/* #endregion t8-logic */

type EditTarget = { dimension: ProfileDimensionKey; index: number | null }

/**
 * 技术画像页（AC-2）：读最新画像 → 5 维卡片 + 溯源源文 → 逐条行内编辑（PATCH 成功才替换）。
 * 服务端是唯一权威（TECHNICAL §4）：刷新只靠 `GET /api/profiles/latest`，PATCH 以响应体为真值，
 * 不做全局乐观更新；404 是引导态（空态），不是错误态。
 */
export default function ProfilePage() {
  const profileAsync = useAsync((signal) => api.latestProfile(signal), [])
  const location = useLocation()

  /**
   * 一次性合并摘要（DESIGN §2.2 / §7-1）：只由「上传 → 生成/合并」那一趟的 `location.state` 带入，
   * 刷新即消失，不落 localStorage、不扩 `GET /api/profiles/latest` 的持久契约。useState 初始化函数只跑一次。
   */
  const [mergeSummary] = useState<ProfileMergeSummary | null>(() => readMergeSummary(location.state))
  const [historyOpen, setHistoryOpen] = useState<{ skills: boolean; projects: boolean }>({
    skills: false,
    projects: false,
  })
  /**
   * r4 D-4：一次性跳转信号用**计数器**而非布尔（重复点击也能重放滚动/聚焦），
   * 并放在 effect 里执行——保证「展开态已提交 DOM」之后再滚动与聚焦。
   */
  const [historyJump, setHistoryJump] = useState(0)
  const skillsHistoryRef = useRef<HTMLDivElement | null>(null)
  const projectsHistoryRef = useRef<HTMLDivElement | null>(null)

  /** 已保存的画像：base 记下「保存时服务端那一版」的 updated_at，服务端刷新出新版就让位给它。 */
  const [patched, setPatched] = useState<{ base: string | null; profile: Profile } | null>(null)
  const [edit, setEdit] = useState<EditTarget | null>(null)
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [retryPatch, setRetryPatch] = useState<ProfilePatch | null>(null)

  const remote = profileAsync.data
  const baseId = remote?.updated_at ?? null
  const profile = patched !== null && patched.base === baseId ? patched.profile : remote

  const view: 'gate' | 'empty' | 'error' | 'ready' =
    profile === null
      ? profileAsync.status === 'error'
        ? profileAsync.error?.status === 404
          ? 'empty'
          : 'error'
        : 'gate'
      : 'ready'

  const entries = profile === null ? null : dimensionEntries(profile)
  const truncationNote = resumeTruncationNote(profile)

  /** 历史能力 / 历史项目条数（摘要条入口按钮的显示条件，AC-12：0 项 = 不渲染）。 */
  const historyCounts = {
    skills: profile === null ? 0 : historicalSkills(profile).length,
    projects: profile === null ? 0 : historicalProjects(profile).length,
  }
  const historyTotal = historyCounts.skills + historyCounts.projects
  const historyControls = (['skills', 'projects'] as const)
    .filter((dimension) => historyCounts[dimension] > 0)
    .map((dimension) => HISTORY_GROUP_ID[dimension])

  /** 入口：展开两个历史分组 → 递增跳转信号（滚动与聚焦由下面的 effect 完成）。 */
  const viewHistory = () => {
    setHistoryOpen({ skills: true, projects: true })
    setHistoryJump((current) => current + 1)
  }

  useEffect(() => {
    if (historyJump === 0 || profile === null) return
    // 取**第一个已渲染**（计数 >0）的容器：只有它才真正存在于 DOM 里
    const counts = {
      skills: historicalSkills(profile).length,
      projects: historicalProjects(profile).length,
    }
    const dimension: 'skills' | 'projects' = counts.skills > 0 ? 'skills' : 'projects'
    if (counts[dimension] === 0) return
    const container = dimension === 'skills' ? skillsHistoryRef.current : projectsHistoryRef.current
    if (container === null) return
    container.scrollIntoView({ block: 'center', behavior: 'smooth' })
    // preventScroll：滚动已由上一行完成，避免 focus 再跳一次（AC-11）
    container.focus({ preventScroll: true })
  }, [historyJump, profile])

  const submitPatch = async (patch: ProfilePatch | null): Promise<boolean> => {
    if (profile === null) return false
    if (patch === null) {
      setEditError('这一项暂不支持行内编辑')
      return false
    }
    setSaving(true)
    setEditError(null)
    setRetryPatch(null)
    try {
      const updated = await api.patchProfile(profile.id, patch)
      setPatched({ base: baseId, profile: nextProfile(profile, { ok: true, profile: updated }) })
      return true
    } catch (error) {
      const message = error instanceof ApiError ? error.message : '保存失败，请重试一次'
      setEditError(message)
      setRetryPatch(patch)
      return false
    } finally {
      setSaving(false)
    }
  }

  const saveEdit = async (values: Record<string, string>): Promise<void> => {
    if (profile === null || edit === null) return
    const patch =
      edit.index === null
        ? buildDimensionPatch(profile, edit.dimension, values)
        : buildEntryPatch(profile, edit.dimension, edit.index, values)
    if (await submitPatch(patch)) setEdit(null)
  }

  const deleteEntry = async (entryKey: string): Promise<void> => {
    if (profile === null) return
    const parsed = parseEntryKey(entryKey)
    if (parsed === null) return
    await submitPatch(buildDeletePatch(profile, parsed.dimension, parsed.index))
  }

  const startEdit = (dimension: ProfileDimensionKey, index: number | null) => {
    setEditError(null)
    setRetryPatch(null)
    setEdit({ dimension, index })
  }

  const cancelEdit = () => {
    setEdit(null)
    setEditError(null)
  }

  const editorFields =
    profile !== null && edit !== null
      ? edit.index === null
        ? dimensionEditorFields(profile, edit.dimension)
        : entryEditorFields(profile, edit.dimension, edit.index)
      : []

  /**
   * 技能 / 项目卡下方的增量可视区（AC-6 + AC-7）：
   * ①多证据折叠（旧→新、带来源文件名与日期），只在 ≥2 条时出现（单条已由卡片内的溯源按钮展示）；
   * ②历史分组（本次简历未出现的能力/项目）——用徽章区分、**不降对比度**（禁 opacity，DESIGN anti-pattern）。
   */
  const evidenceExtras = (dimension: 'skills' | 'projects') => {
    if (profile === null) return null
    const source: TrackedEntry[] = dimension === 'skills' ? profile.skills : profile.projects
    const foldable = source.filter((item) => !isHistorical(item) && evidenceOf(item).length >= 2)
    const historical = source.filter((item) => isHistorical(item))
    if (foldable.length === 0 && historical.length === 0) return null

    const open = historyOpen[dimension]

    return (
      <div className="sc-actions">
        {foldable.length > 0 ? (
          <div className="sc-evidence-list" aria-label="能力证据">
            {foldable.map((item) => (
              <EvidenceList
                key={`${dimension}-evidence-${item.name}`}
                evidence={evidenceOf(item)}
                label={`${item.name} · 证据 ${evidenceOf(item).length} 条 · 旧→新`}
              />
            ))}
          </div>
        ) : null}

        {historical.length > 0 ? (
          /*
           * 历史分组容器（r4 D-4）：id / ref / 焦点落在**始终渲染**的分组外壳上，
           * 这样 `aria-controls` 在展开前后都能解析到真实元素（AC-11），
           * 展开后焦点环包住的也是「开关 + 历史条目」这一整块，滚动落点即分组本身。
           */
          <div
            id={HISTORY_GROUP_ID[dimension]}
            ref={dimension === 'skills' ? skillsHistoryRef : projectsHistoryRef}
            tabIndex={-1}
            className="sc-hist sc-hist-group"
            aria-label={dimension === 'skills' ? '历史能力分组' : '历史项目分组'}
          >
            <button
              type="button"
              className={open ? 'sc-evidence-chip is-expanded' : 'sc-evidence-chip'}
              aria-expanded={open}
              onClick={() =>
                setHistoryOpen((current) => ({ ...current, [dimension]: !current[dimension] }))
              }
            >
              <span>
                {`${open ? '▾' : '▸'} ${dimension === 'skills' ? '历史能力' : '历史项目'} ${historical.length} 项（本次简历未出现 · 不参与出题与诊断）`}
              </span>
            </button>

            {open ? (
              <div className="sc-evidence-list" aria-label="历史条目">
                {historical.map((item) => (
                  <div key={`${dimension}-historical-${item.name}`} className="sc-evidence-item">
                    <div className="sc-chips">
                      <Chip label={item.name} />
                      <Chip label="历史" />
                      <Chip label={`证据 ${evidenceOf(item).length} 条`} />
                    </div>
                    <EvidenceList evidence={evidenceOf(item)} />
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">你的技术画像</h1>
        <p className="sc-page-sub">
          {profile === null
            ? '读取简历后自动生成 5 个维度，每条结论都带简历原文出处'
            : `${sourceCount(profile)} 条溯源 · ${profile.skills.length} 个技能 · ${profile.projects.length} 段项目 · 可选编辑后开始测评`}
        </p>
      </header>

      {mergeSummary !== null ? (
        <MergeSummaryBar
          summary={mergeSummary}
          historyCount={historyTotal}
          historyControls={historyControls}
          onViewHistory={viewHistory}
        />
      ) : null}

      {view === 'gate' ? (
        <PhaseLoader title="正在读取你的最新画像" phases={['读取最新画像']} active={0} />
      ) : null}

      {view === 'empty' ? (
        <EmptyState
          reason="还没有画像。先上传一份简历（PDF / DOCX / TXT，≤10MB），AI 会据此建立可溯源的 5 维画像。"
          actionLabel="上传简历"
          actionTo="/"
        />
      ) : null}

      {view === 'error' && profileAsync.error ? (
        <InlineError message={profileAsync.error.message} onRetry={profileAsync.reload} />
      ) : null}

      {view === 'ready' && profile !== null && entries !== null ? (
        <>
          {truncationNote ? <p className="sc-meta-line">{truncationNote}</p> : null}

          {editError !== null && edit === null ? (
            <InlineError
              message={editError}
              onRetry={
                retryPatch === null
                  ? undefined
                  : () => {
                      void submitPatch(retryPatch)
                    }
              }
            />
          ) : null}

          <div className="sc-grid-2">
            <div>
              {DIMENSIONS.map((item) => (
                <div key={item.key}>
                  <ProfileDimension
                    dimension={item.key}
                    title={item.title}
                    entries={entries[item.key]}
                    value={singleValueOf(profile, item.key)}
                    emptyHint={item.hint}
                    editable={item.editable}
                    editing={edit !== null && edit.dimension === item.key}
                    saving={saving}
                    onEdit={() => startEdit(item.key, null)}
                    onEditEntry={(entryKey) => {
                      const parsed = parseEntryKey(entryKey)
                      if (parsed !== null) startEdit(parsed.dimension, parsed.index)
                    }}
                    onDeleteEntry={(entryKey) => {
                      void deleteEntry(entryKey)
                    }}
                    editor={
                      edit !== null && edit.dimension === item.key ? (
                        <ProfileEditor
                          key={`${item.key}#${edit.index === null ? 'dimension' : edit.index}`}
                          fields={editorFields}
                          saving={saving}
                          error={editError}
                          onSave={(values) => {
                            void saveEdit(values)
                          }}
                          onCancel={cancelEdit}
                        />
                      ) : null
                    }
                  />
                  {item.key === 'skills' || item.key === 'projects' ? evidenceExtras(item.key) : null}
                </div>
              ))}
            </div>

            <aside>
              <p className="sc-mono">{`${confirmedDimensions(profile)}/5 维度已确认`}</p>
              <p className="sc-meta-line">编辑后以服务端返回为准；保存失败不会改动已保存的画像。</p>
              <div className="sc-btn-row">
                <Link className="sc-btn sc-btn--primary" to="/interview">
                  开始模拟面试
                </Link>
                <Link className="sc-btn sc-btn--secondary" to="/exam">
                  改为笔试
                </Link>
                <Link className="sc-btn sc-btn--secondary" to="/">
                  重新上传简历
                </Link>
              </div>
            </aside>
          </div>
        </>
      ) : null}
    </section>
  )
}
