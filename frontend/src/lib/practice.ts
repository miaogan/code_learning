/**
 * 练习页的中文展示映射与纯逻辑（r11）：**业务文案的唯一出处**（DESIGN r11 §1.3 / TECHNICAL §6.6）。
 *
 * 为什么全在这里：页面与 5 个小组件都不许写业务字面文案（「暂无解析」「10 题」「只看错题」…），
 * 集中一处才能被 vitest 直接断言（本项目无 DOM 测试库，纯函数是唯一可靠的前端断言方式）。
 * 组件只消费这里导出的常量 / 函数，不自己拼字符串。
 */
import { DIRECTIONS, subDirectionsOf } from './questionDirections'
import type {
  ExamDifficulty,
  ExamKind,
  PracticeDirectionFilter,
  PracticeDifficultyFilter,
  PracticeEssentialityFilter,
  PracticeLanguageFilter,
  PracticeLimit,
  PracticeScope,
  QuestionEssentiality,
  QuestionLanguage,
} from '../api/types'

/**
 * 六个筛选维度 + 题量：页面持有这一整块状态（无全局 store，刷新即重置）。
 *
 * 筛选维度均为**多选**（「全部」哨兵不与其他具体项并存，由 `MultiChipRow` 折叠）：
 * 空数组 = 全部（仅二级方向会出现，语义同「不聚焦」）。
 */
export interface PracticeFiltersState {
  language: PracticeLanguageFilter[]
  direction: PracticeDirectionFilter[]
  /** r50：空数组 = 不聚焦；取值闭集由 `allowedSubDirections(direction)` 派生。 */
  sub_direction: string[]
  difficulty: PracticeDifficultyFilter[]
  essentiality: PracticeEssentialityFilter[]
  scope: PracticeScope[]
  /** 题量是数量档位，不是可并集的筛选集合，仍单选。 */
  limit: PracticeLimit
}

/** 默认筛选：全部 + 10 题（与服务端默认值逐字一致，避免首屏多发一次无效请求）。 */
export const DEFAULT_PRACTICE_FILTERS: PracticeFiltersState = {
  language: ['all'],
  direction: ['all'],
  sub_direction: [],
  difficulty: ['all'],
  essentiality: ['all'],
  scope: ['all'],
  limit: 10,
}

/**
 * 「全部」判定：`MultiChipRow` 已保证「勾满具体项」折叠成 `[allValue]`，
 * 因此这里只需看空数组与哨兵（展示层与放宽建议共用，不另算一份）。
 */
export function isAllSelection<T extends string | number>(
  values: readonly T[],
  allValue: T,
): boolean {
  return values.length === 0 || values.includes(allValue)
}

/** 语言闭集的展示顺序（后端 `rules.LANGUAGES` 的镜像顺序：通用题排首位）。 */
const LANGUAGE_ORDER: QuestionLanguage[] = [
  '',
  'python',
  'java',
  'go',
  'html',
  'css',
  'js',
  'ts',
  'vue3',
  'react',
]

/**
 * 语言 → 中文标签。**`''` 是闭集成员**（通用 / 算法题），不是「全部」——
 * 「全部」是 `'all'`（`rules.FILTER_ANY`），两条语义不得混用（TECHNICAL §5.1）。
 */
export const LANGUAGE_LABEL: Record<QuestionLanguage, string> = {
  '': '通用',
  python: 'Python',
  java: 'Java',
  go: 'Go',
  html: 'HTML',
  css: 'CSS',
  js: 'JavaScript',
  ts: 'TypeScript',
  vue3: 'Vue 3',
  react: 'React',
}

/** 题型：`text` 是简答题（不进练习池），保留键只为让 Record 穷举、typecheck 在闭集变化时红。 */
export const KIND_LABEL: Record<ExamKind, string> = {
  single: '单选',
  multiple: '多选',
  judge: '判断',
  text: '简答',
}

export const DIFFICULTY_LABEL: Record<ExamDifficulty, string> = {
  basic: '基础',
  intermediate: '进阶',
  challenge: '挑战',
}

export const ESSENTIALITY_LABEL: Record<QuestionEssentiality, string> = {
  must_know: '必须掌握',
  advanced: '进阶',
  nice_to_know: '加分项',
}

export const SCOPE_LABEL: Record<PracticeScope, string> = {
  all: '全部',
  unseen: '只看未做过',
  wrong: '只看错题',
}

/** 语言筛选的展示名（`'all'` 与 `''` 必须给出不同文案，否则用户无法区分「全部」与「通用题」）。 */
export function languageLabel(value: PracticeLanguageFilter): string {
  return value === 'all' ? '全部语言' : LANGUAGE_LABEL[value]
}

export function directionLabel(value: PracticeDirectionFilter): string {
  return value === 'all' ? '全部方向' : value
}

/** 语言 chip 组：11 个（全部 + 通用 + 9 门语言），顺序与 `rules.LANGUAGES` 一致。 */
export function languageChips(): { value: PracticeLanguageFilter; label: string }[] {
  return [
    { value: 'all', label: '全部' },
    ...LANGUAGE_ORDER.map((language) => ({
      value: language as PracticeLanguageFilter,
      label: LANGUAGE_LABEL[language],
    })),
  ]
}

/**
 * 方向闭集与展示顺序（与后端 `rules.DIRECTIONS` 同源，类型取契约镜像）。
 * `satisfies Record<...>` 是编译期门禁：契约新增方向而此处漏项即 typecheck 红，
 * 不会出现「新方向静默缺 chip」。
 */
const DIRECTION_LABEL = {
  前端: '前端',
  后端: '后端',
  算法与数据结构: '算法与数据结构',
  计算机基础: '计算机基础',
  'AI 工程': 'AI 工程',
  '中间件与运维': '中间件与运维',
  'SQL 与数据库': 'SQL 与数据库',
  研发工程实践: '研发工程实践',
} satisfies Record<Exclude<PracticeDirectionFilter, 'all'>, string>

/** 方向 chip 组：四方向 + 全部（唯一来源是 `DIRECTION_LABEL`，不在函数内重复字面量）。 */
export function directionChips(): { value: PracticeDirectionFilter; label: string }[] {
  return [
    { value: 'all', label: '全部' },
    ...(Object.keys(DIRECTION_LABEL) as Exclude<PracticeDirectionFilter, 'all'>[]).map(
      (direction) => ({ value: direction, label: DIRECTION_LABEL[direction] }),
    ),
  ]
}

/**
 * r50：所选方向下**可选**的二级方向并集。「全部」时返回全库子方向
 * （服务端会把合法子方向自动归一到其父方向，见 `_resolve_focus`）。
 */
export function allowedSubDirections(direction: PracticeDirectionFilter[]): string[] {
  if (isAllSelection(direction, 'all')) {
    return DIRECTIONS.flatMap(subDirectionsOf)
  }
  const merged = new Set<string>()
  direction.forEach((name) => subDirectionsOf(name).forEach((sub) => merged.add(sub)))
  return Array.from(merged)
}

/** r50：二级方向 chip 组；未选方向时为空数组（由筛选卡显示「先选方向」提示）。 */
export function subDirectionChips(
  direction: PracticeDirectionFilter[],
): { value: string; label: string }[] {
  const subs = allowedSubDirections(direction)
  if (isAllSelection(direction, 'all') || subs.length === 0) return []
  return [{ value: '', label: '全部' }, ...subs.map((sub) => ({ value: sub, label: sub }))]
}

export function difficultyChips(): { value: PracticeDifficultyFilter; label: string }[] {
  return [
    { value: 'all', label: '全部' },
    { value: 'basic', label: DIFFICULTY_LABEL.basic },
    { value: 'intermediate', label: DIFFICULTY_LABEL.intermediate },
    { value: 'challenge', label: DIFFICULTY_LABEL.challenge },
  ]
}

export function essentialityChips(): { value: PracticeEssentialityFilter; label: string }[] {
  return [
    { value: 'all', label: '全部' },
    { value: 'must_know', label: ESSENTIALITY_LABEL.must_know },
    { value: 'advanced', label: ESSENTIALITY_LABEL.advanced },
    { value: 'nice_to_know', label: ESSENTIALITY_LABEL.nice_to_know },
  ]
}

export function scopeChips(): { value: PracticeScope; label: string }[] {
  return [
    { value: 'all', label: SCOPE_LABEL.all },
    { value: 'unseen', label: SCOPE_LABEL.unseen },
    { value: 'wrong', label: SCOPE_LABEL.wrong },
  ]
}

/** 题量文案：`0` = 本次全部命中（DESIGN §2.1：不要写「0 题」）。 */
export function limitLabel(limit: PracticeLimit): string {
  return limit === 0 ? '全部' : `${limit} 题`
}

export function limitChips(): { value: PracticeLimit; label: string }[] {
  return ([10, 20, 0] as PracticeLimit[]).map((limit) => ({ value: limit, label: limitLabel(limit) }))
}

/** 正确率：分母 0 / 非法值一律「—」（不写 `NaN%`，也不写 `0%` 冒充成绩）。 */
export function accuracyText(correct: number, total: number): string {
  if (!Number.isFinite(correct) || !Number.isFinite(total) || total <= 0) return '—'
  const percent = Math.round((Math.max(0, correct) / total) * 100)
  return `${percent}%`
}

/** 错题时间：UTC ISO8601 → 本地 `MM-dd HH:mm`；非法串原样回退（不显示 Invalid Date）。 */
export function formatWrongTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 正确答案回显：数组写 `A、C`（多选不缩写），字符串原样，空值给「未记录」。 */
export function answerText(answer: string[] | string | null | undefined): string {
  if (answer === null || answer === undefined) return '未记录'
  if (Array.isArray(answer)) return answer.length === 0 ? '未记录' : answer.join('、')
  return answer === '' ? '未记录' : answer
}

/**
 * 错题行的一行题干预览：去围栏、去行内反引号、空白压成单空格、超长截断。
 * 行内截断只是**视觉兜底**，真正的省略号由 CSS `text-overflow` 出；两者一致才不会出现「双省略」。
 */
export function promptPreview(prompt: string, max = 88): string {
  const flat = prompt
    .replace(/```[^\n]*\n?/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/`/g, '')
    .trim()
  return flat.length > max ? `${flat.slice(0, max)}…` : flat
}

/** 0 命中时可点的「放宽」建议（文案即按钮文字，点击后把对应维度设为「全部」）。 */
export const RELAX_OPTIONS: { label: string; patch: Partial<PracticeFiltersState> }[] = [
  { label: '难度=全部', patch: { difficulty: ['all'] } },
  { label: '必备度=全部', patch: { essentiality: ['all'] } },
  { label: '方向=全部', patch: { direction: ['all'], sub_direction: [] } },
  { label: '二级方向=全部', patch: { sub_direction: [] } },
  { label: '语言=全部', patch: { language: ['all'] } },
  { label: '范围=全部', patch: { scope: ['all'] } },
]

/**
 * 0 命中时给出至多 3 条建议：只建议「当前不是全部」的维度（建议一个已经是全部的维度毫无意义）。
 * 全部维度都已是最宽时（题库真的空）返回空数组，由空态承接。
 */
export function relaxSuggestions(filters: PracticeFiltersState): string[] {
  const active: string[] = []
  if (!isAllSelection(filters.difficulty, 'all')) active.push('难度=全部')
  if (!isAllSelection(filters.essentiality, 'all')) active.push('必备度=全部')
  if (!isAllSelection(filters.direction, 'all')) active.push('方向=全部')
  if (!isAllSelection(filters.sub_direction, '')) active.push('二级方向=全部')
  if (!isAllSelection(filters.language, 'all')) active.push('语言=全部')
  if (!isAllSelection(filters.scope, 'all')) active.push('范围=全部')
  return active.slice(0, 3)
}

/** 多选维度的一行文案：全选取「全部 X」，否则用「、」并列具体项（中文标签，不写枚举值）。 */
function choiceText<T extends string>(
  values: readonly T[],
  allValue: T,
  allLabel: string,
  labelOf: (value: T) => string,
): string {
  return isAllSelection(values, allValue) ? allLabel : values.map(labelOf).join('、')
}

/** 完成态「本次筛选：…」：四个维度并列，避免只写「全部」让用户看不出本轮条件。 */
export function filtersLabel(filters: PracticeFiltersState): string {
  const parts = [
    choiceText(
      filters.language,
      'all',
      '全部语言',
      // 走到 labelOf 时一定不是「全部」哨兵，收窄后才是 QUESTION_LANGUAGE 闭集
      (value) => LANGUAGE_LABEL[value as Exclude<PracticeLanguageFilter, 'all'>],
    ),
    choiceText(filters.direction, 'all', '全部方向', (value) => value),
    choiceText(
      filters.difficulty,
      'all',
      '全部难度',
      (value) => DIFFICULTY_LABEL[value as Exclude<PracticeDifficultyFilter, 'all'>],
    ),
    choiceText(
      filters.essentiality,
      'all',
      '全部必备度',
      (value) => ESSENTIALITY_LABEL[value as Exclude<PracticeEssentialityFilter, 'all'>],
    ),
  ]
  // r50：聚焦的二级方向必须出现在完成态描述里，否则用户看不出本轮练的是哪一块
  if (!isAllSelection(filters.sub_direction, '')) {
    parts.push(filters.sub_direction.join('、'))
  }
  // 「错题重练」一轮的 scope 必须是可见条件，否则用户看不出这轮为什么只有错题
  if (!isAllSelection(filters.scope, 'all')) {
    parts.push(filters.scope.map((value) => SCOPE_LABEL[value]).join('、'))
  }
  return parts.join(' · ')
}

/** 循环切换 tab 时的角标文案：0 条时不加数字（「错题本 0」是噪音）。 */
export function wrongTabLabel(total: number): string {
  return total > 0 ? `错题本 ${total}` : '错题本'
}

/* ---------------- 五态与错误文案（DESIGN §2.6 逐字；组件不得另写字面量） ---------------- */

/** 筛选 0 命中（200 + 空列表，不是错误）。 */
export const NO_HIT_MESSAGE = '该组合下没有题目，试试放宽难度或必备度'
/** 题库未就绪（全库 0 题）。 */
export const EMPTY_BANK_REASON = '题库未就绪，暂时没有可练习的题目'
/** 题单加载失败（保留筛选，可重试）。 */
export const PAPER_ERROR_FALLBACK = '题单加载失败，请稍后重试'
/** 判分失败（保留已选答案，可重试）。 */
export const ANSWER_ERROR_MESSAGE = '判分失败，你的选择已保留，可直接重试'
/** 错题本空态原因句（必须给出口，不许只写「暂无数据」）。 */
export const WRONG_BOOK_EMPTY_REASON = '练习里答错的题会自动进来，答对一次就移出'
/** 未选答案就点提交（不直接禁用按钮，避免死按钮）。 */
export const NEED_ANSWER_MESSAGE = '先选一个答案，再提交'
/** 统计请求失败（命中行降级文案）。 */
export const STATS_ERROR_MESSAGE = '题库统计读取失败，可稍后重试'

/**
 * 从 `/practice` 的 URL query 解析初始筛选（报告页「7 天计划」的专项练习链接用）。
 * 只接受闭集内取值：未知 / 非法 / 缺省一律回落默认值，不抛错、不让页面白屏。
 *
 * 多选写法两种都吃：重复键（`language=python&language=go`）与逗号并列（`language=python,go`）；
 * 勾满全部具体项（或带 `all`）折叠成 `["all"]`，与 chip 交互后的状态同形。
 */
export function parsePracticeSearch(search: string): PracticeFiltersState {
  const params = new URLSearchParams(search)
  const languageOptions = languageChips()
  const directionOptions = directionChips()
  const difficultyOptions = difficultyChips()
  const essentialityOptions = essentialityChips()
  const scopeOptions = scopeChips()
  const concrete = <T extends string>(options: { value: T }[], allValue: T): T[] =>
    options.filter((chip) => chip.value !== allValue).map((chip) => chip.value)

  const language = readChoices(
    params,
    'language',
    new Set<string>(languageOptions.map((chip) => chip.value)),
    'all',
    concrete(languageOptions, 'all'),
  )
  const direction = readChoices(
    params,
    'direction',
    new Set<string>(directionOptions.map((chip) => chip.value)),
    'all',
    concrete(directionOptions, 'all'),
  )
  // r50：子方向必须落在所选方向的闭集里（direction=all 时允许全库子方向，服务端会锁父方向）；
  // 越界值与 direction 一起回落默认，不让脏 query 选出空题单。
  const allowedSubs = allowedSubDirections(direction)
  // 二级方向的「全部」哨兵是空串；状态里统一用空数组表示「不聚焦」，故过滤掉哨兵。
  const sub_direction = readChoices(
    params,
    'sub',
    new Set<string>(allowedSubs),
    '',
    allowedSubs,
  ).filter((sub) => sub !== '')
  const difficulty = readChoices(
    params,
    'difficulty',
    new Set<string>(difficultyOptions.map((chip) => chip.value)),
    'all',
    concrete(difficultyOptions, 'all'),
  )
  const essentiality = readChoices(
    params,
    'essentiality',
    new Set<string>(essentialityOptions.map((chip) => chip.value)),
    'all',
    concrete(essentialityOptions, 'all'),
  )
  const scope = readChoices(
    params,
    'scope',
    new Set<string>(scopeOptions.map((chip) => chip.value)),
    'all',
    concrete(scopeOptions, 'all'),
  )

  const limitRaw = params.get('limit')
  const limit = limitRaw === null ? null : Number(limitRaw)

  return {
    language,
    direction,
    sub_direction,
    difficulty,
    essentiality,
    scope,
    limit:
      limit !== null && limitChips().some((chip) => chip.value === limit)
        ? (limit as PracticeLimit)
        : DEFAULT_PRACTICE_FILTERS.limit,
  }
}

/** 读一个多选维度：只留闭集内取值；无有效值回落「全部」，勾满具体项折叠回「全部」。 */
function readChoices<T extends string>(
  params: URLSearchParams,
  key: string,
  allowed: ReadonlySet<string>,
  allValue: T,
  concreteValues: readonly T[],
): T[] {
  const picked = params
    .getAll(key)
    .flatMap((raw) => raw.split(','))
    .filter((value) => allowed.has(value)) as T[]
  if (picked.length === 0) return [allValue]
  if (picked.includes(allValue) || concreteValues.every((value) => picked.includes(value))) {
    return [allValue]
  }
  return concreteValues.filter((value) => picked.includes(value))
}
