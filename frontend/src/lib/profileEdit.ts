import type {
  Evidence,
  Profile,
  ProfileMergeSummary,
  ProfilePatch,
  ProfileProject,
  ProfileSkill,
} from '../api/types'
import type { DimensionEntry, ProfileDimensionKey } from '../components/profile/ProfileDimension'
import type { EditorField } from '../components/profile/ProfileEditor'
import { joinMeta, textOrEmpty } from './profileText'

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
function entryKeyOf(dimension: ProfileDimensionKey, index: number): string {
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
export type TrackedEntry = {
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
function normalizeMergeSummary(raw: unknown): ProfileMergeSummary | null {
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
              // r8：role/period 契约可空（提示词允许 null），拼接统一走 joinMeta，
              // 两侧皆空返回 '' ⇒ ProfileDimension 的 `entry.meta ? … : null` 直接吞掉，不渲染空行。
              meta: joinMeta([item.role, item.period]),
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
function splitList(raw: string | undefined): string[] {
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
function parseYears(raw: string | undefined): number | null {
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
      // r8：编辑框清空 = 用户显式「我不知道」，出站存 null（不是 ''），与 target_role 既有写法同口径。
      role: trimToNull(textOrEmpty(values.role ?? target.role)),
      period: trimToNull(textOrEmpty(values.period ?? target.period)),
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
      // r8：编辑框 value 必须是 string（受控输入不收 null），未知项以空串进入编辑，
      // 用户不改则原样 null 回写（见 buildEntryPatch 的 trimToNull）。
      // D-2：空字段给占位提示，和「技术栈 / 年限」一致地说明这是「简历没写」而非加载失败。
      {
        key: 'role',
        label: '角色',
        kind: 'text',
        value: textOrEmpty(target.role),
        placeholder: '简历未填写，可留空',
      },
      {
        key: 'period',
        label: '时间',
        kind: 'text',
        value: textOrEmpty(target.period),
        placeholder: '简历未填写，可留空',
      },
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
