/**
 * 练习页的中文展示映射与纯逻辑（r11）：**业务文案的唯一出处**（DESIGN r11 §1.3 / TECHNICAL §6.6）。
 *
 * 为什么全在这里：页面与 5 个小组件都不许写业务字面文案（「暂无解析」「10 题」「只看错题」…），
 * 集中一处才能被 vitest 直接断言（本项目无 DOM 测试库，纯函数是唯一可靠的前端断言方式）。
 * 组件只消费这里导出的常量 / 函数，不自己拼字符串。
 */
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

/** 五个筛选维度 + 题量：页面持有这一整块状态（无全局 store，刷新即重置）。 */
export interface PracticeFiltersState {
  language: PracticeLanguageFilter
  direction: PracticeDirectionFilter
  difficulty: PracticeDifficultyFilter
  essentiality: PracticeEssentialityFilter
  scope: PracticeScope
  limit: PracticeLimit
}

/** 默认筛选：全部 + 10 题（与服务端默认值逐字一致，避免首屏多发一次无效请求）。 */
export const DEFAULT_PRACTICE_FILTERS: PracticeFiltersState = {
  language: 'all',
  direction: 'all',
  difficulty: 'all',
  essentiality: 'all',
  scope: 'all',
  limit: 10,
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
  { label: '难度=全部', patch: { difficulty: 'all' } },
  { label: '必备度=全部', patch: { essentiality: 'all' } },
  { label: '方向=全部', patch: { direction: 'all' } },
  { label: '语言=全部', patch: { language: 'all' } },
  { label: '范围=全部', patch: { scope: 'all' } },
]

/**
 * 0 命中时给出至多 3 条建议：只建议「当前不是全部」的维度（建议一个已经是全部的维度毫无意义）。
 * 全部维度都已是最宽时（题库真的空）返回空数组，由空态承接。
 */
export function relaxSuggestions(filters: PracticeFiltersState): string[] {
  const active: string[] = []
  if (filters.difficulty !== 'all') active.push('难度=全部')
  if (filters.essentiality !== 'all') active.push('必备度=全部')
  if (filters.direction !== 'all') active.push('方向=全部')
  if (filters.language !== 'all') active.push('语言=全部')
  if (filters.scope !== 'all') active.push('范围=全部')
  return active.slice(0, 3)
}

/** 完成态「本次筛选：…」：四个维度并列，避免只写「全部」让用户看不出本轮条件。 */
export function filtersLabel(filters: PracticeFiltersState): string {
  const parts = [
    languageLabel(filters.language),
    directionLabel(filters.direction),
    filters.difficulty === 'all' ? '全部难度' : DIFFICULTY_LABEL[filters.difficulty],
    filters.essentiality === 'all' ? '全部必备度' : ESSENTIALITY_LABEL[filters.essentiality],
  ]
  // 「错题重练」一轮的 scope 必须是可见条件，否则用户看不出这轮为什么只有错题
  if (filters.scope !== 'all') parts.push(SCOPE_LABEL[filters.scope])
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
 */
export function parsePracticeSearch(search: string): PracticeFiltersState {
  const params = new URLSearchParams(search)
  const languages = new Set<string>(languageChips().map((chip) => chip.value))
  const directions = new Set<string>(directionChips().map((chip) => chip.value))
  const difficulties = new Set<string>(difficultyChips().map((chip) => chip.value))
  const essentialities = new Set<string>(essentialityChips().map((chip) => chip.value))
  const scopes = new Set<string>(scopeChips().map((chip) => chip.value))

  const language = params.get('language')
  const direction = params.get('direction')
  const difficulty = params.get('difficulty')
  const essentiality = params.get('essentiality')
  const scope = params.get('scope')
  const limitRaw = params.get('limit')
  const limit = limitRaw === null ? null : Number(limitRaw)

  return {
    language:
      language !== null && languages.has(language)
        ? (language as PracticeLanguageFilter)
        : DEFAULT_PRACTICE_FILTERS.language,
    direction:
      direction !== null && directions.has(direction)
        ? (direction as PracticeDirectionFilter)
        : DEFAULT_PRACTICE_FILTERS.direction,
    difficulty:
      difficulty !== null && difficulties.has(difficulty)
        ? (difficulty as PracticeDifficultyFilter)
        : DEFAULT_PRACTICE_FILTERS.difficulty,
    essentiality:
      essentiality !== null && essentialities.has(essentiality)
        ? (essentiality as PracticeEssentialityFilter)
        : DEFAULT_PRACTICE_FILTERS.essentiality,
    scope:
      scope !== null && scopes.has(scope) ? (scope as PracticeScope) : DEFAULT_PRACTICE_FILTERS.scope,
    limit:
      limit !== null && limitChips().some((chip) => chip.value === limit)
        ? (limit as PracticeLimit)
        : DEFAULT_PRACTICE_FILTERS.limit,
  }
}
