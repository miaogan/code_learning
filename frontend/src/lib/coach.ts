/**
 * 报告「提升路线」三块（r7）的**纯函数与中文文案**单一出处（无 DOM、无请求，vitest 可直接测）。
 *
 * 为什么单独成模块：三态判定（`null` 旧报告 / `[]` 本块无内容 / 非空）、折叠上限、
 * 错误率与计数文案、差距文案、润色跳转 URL 如果散落在四个组件里，就会出现四份
 * 「`?? []`」「`Math.round(x*100)`」，任一份漂移都会让页面与 `.md` 对不上（AC-12/AC-13）。
 *
 * 文案与 `backend/app/services/coach_copy.py` **逐字一致**（门禁
 * `test_engineering_gates.py::test_r7_copy_parity` 逐条断言）；服务端已给的原因
 * （`resume_pointers_notice` / `role_fit.notice`）由页面直接渲染，不在这里二次拼。
 */
import type { PolishSection } from '../api/types'

// === 文案镜像（与 backend/app/services/coach_copy.py 的常量逐字相同）=============

/** `Report.<block>` 为 `null`：旧报告（字段未落库），与「新报告但本块为空」严格区分。 */
const LEGACY_BLOCK_NOTICE = '旧报告不含该区块，重新生成可补全'
/** `Report.weakness_map === []`：本次没有任何已计分客观题可聚合。 */
const WEAKNESS_EMPTY = '本次测评还没有可统计的计分题'
/** `Report.resume_pointers === []` 且没有简历正文可定位（跳过 AI 调用）。 */
const RESUME_NO_TEXT = '还没有可定位的简历正文，先上传简历再回来看改进要点'
/** `Report.resume_pointers === []` 且正文存在但 AI 一路失败 / 未配置 Key（降级）。 */
const RESUME_AI_FALLBACK = '简历要点暂时没生成出来，可以先去润色页逐条查看'
/** `Report.role_fit.model === null`：目标岗位未命中内置能力模型。 */
const ROLE_NO_MODEL = '暂无该岗位的能力模型'
/** 无模型时给出的下一步建议（与上面那句成对出现，避免只给结论不给动作）。 */
const ROLE_NO_MODEL_HINT = '可以先按上面的薄弱地图补，或在简历画像里填写更常见的岗位名'

/**
 * 三块区块的降级 / 空态文案。
 * 只在「服务端没给原因」时兜底；正常路径优先渲染服务端下发的 `notice`（两端各写一份必然漂移）。
 */
export const COACH_COPY = {
  legacy: LEGACY_BLOCK_NOTICE,
  weaknessEmpty: WEAKNESS_EMPTY,
  resumeEmpty: RESUME_NO_TEXT,
  resumeFallback: RESUME_AI_FALLBACK,
  roleNoModel: ROLE_NO_MODEL,
  roleNoModelHint: ROLE_NO_MODEL_HINT,
} as const

// === 常量 ======================================================================

/** 首屏先给的薄弱条目数（后端不截断，折叠只是纯前端行为；AC-19）。 */
export const WEAKNESS_FOLD_LIMIT = 8

/** 跳转 URL 里携带 `anchor` 的最大长度：超长原句靠 `focus` 定位即可，URL 不撑爆。 */
const ANCHOR_MAX_CHARS = 120

/** 难度标签：键与 `rules.DIFFICULTIES` 一字不差；未知值原样显示（不吞数据、不报错）。 */
export const DIFFICULTY_LABEL: Record<string, string> = {
  basic: '基础',
  intermediate: '进阶',
  challenge: '挑战',
}

/** 必备度标签：键与 `rules.ESSENTIALITIES` 一字不差。 */
export const ESSENTIALITY_LABEL: Record<string, string> = {
  must_know: '必备',
  advanced: '进阶',
  nice_to_know: '了解',
}

/** 排序说明（不写算法细节，与 DESIGN §2.1 固定文案一致）。 */
export const WEAKNESS_SORT_NOTE = '必备优先 → 错误率高 → 均分低'

// === 三态判定 ==================================================================

/**
 * 区块三态：`legacy` = 字段缺失（旧报告）｜`empty` = 本块无内容｜`ready` = 正常渲染。
 *
 * **禁止 `?? []` 兜底**：`null` 变成空数组会把旧报告误报成「没有计分题」（AC-13）。
 */
export type BlockState = 'legacy' | 'empty' | 'ready'

export function blockStateOf<T>(value: T[] | null | undefined): BlockState {
  if (value === null || value === undefined) return 'legacy'
  if (value.length === 0) return 'empty'
  return 'ready'
}

// === 折叠 ======================================================================

export interface Folded<T> {
  visible: T[]
  /** 被折叠的条数（展开时为 0；表格只渲染 `visible`）。 */
  hiddenCount: number
}

/** 折叠：默认 8 条，展开后全部可见。顺序即入参顺序（前端不排序、不去重）。 */
export function foldWeakness<T>(items: T[], expanded: boolean): Folded<T> {
  if (expanded || items.length <= WEAKNESS_FOLD_LIMIT) {
    return { visible: items.slice(), hiddenCount: 0 }
  }
  return { visible: items.slice(0, WEAKNESS_FOLD_LIMIT), hiddenCount: items.length - WEAKNESS_FOLD_LIMIT }
}

// === 展示文案 ==================================================================

/** 错误率：服务端算好 0–1，这里只做整数百分比（不出现小数错误率）。 */
export function weaknessRateLabel(rate: number): string {
  if (!Number.isFinite(rate)) return '—'
  const clamped = Math.min(1, Math.max(0, rate))
  return `${Math.round(clamped * 100)}%`
}

/**
 * 错误率横条的宽度（0–100）：与 `weaknessRateLabel` **同一夹取口径**，
 * 保证「读到的百分比」与「画出来的长度」不会一个 100% 一个 120%（图例不可与读数矛盾）。
 */
export function weaknessRatePercent(rate: number): number {
  if (!Number.isFinite(rate)) return 0
  return Math.round(Math.min(1, Math.max(0, rate)) * 100)
}

/** 错题计数：与错误率**同屏**出现（错误率单独出现会被误读，AC-2 的反向断言）。 */
export function weaknessCountLabel(wrong: number, total: number): string {
  return `错 ${wrong} / 共 ${total} 题`
}

/**
 * r50：薄弱地图的作用域标签（方向 · 二级方向）。
 * `point` 对面试短板是题型名、不是方向，故这行是**新增信息**而非重复；
 * 旧报告缺 `sub_direction` 时返回 `null`，组件不挂载节点（逐字等价、零占位）。
 */
export function weaknessSubDirectionLabel(item: {
  direction: string
  sub_direction?: string
}): string | null {
  const sub = (item.sub_direction ?? '').trim()
  if (!sub) return null
  const direction = item.direction.trim()
  return direction === '' ? sub : `${direction} · ${sub}`
}

/** 差距：`0` 渲染「达标」而不是 `0`（0 与「未统计」歧义）；负数视为已达标。 */
export function roleGapLabel(gap: number): string {
  if (!Number.isFinite(gap) || gap <= 0) return '达标'
  return String(Math.round(gap))
}

/** 标签查表：未知值原样显示（后端新增档位时前端不白屏、不瞎猜中文）。 */
export function difficultyLabel(value: string): string {
  return DIFFICULTY_LABEL[value] ?? value
}

export function essentialityLabel(value: string): string {
  return ESSENTIALITY_LABEL[value] ?? value
}

// === 润色页跳转 ================================================================

/**
 * `/polish` 定位链接：只携带 `focus` / `section` / `anchor` 三个短参数。
 *
 * `focus` 与 `anchor` 当前同值（逐字相等），但语义分开保留：`anchor` 只是复核用原句，
 * 超长（>120 字）时不带，避免 URL 过长被浏览器/代理截断。
 */
export function polishHref(focusKey: string, section: PolishSection, anchorText: string): string {
  const parts = [`focus=${encodeURIComponent(focusKey)}`, `section=${encodeURIComponent(section)}`]
  if (anchorText.length > 0 && anchorText.length <= ANCHOR_MAX_CHARS) {
    parts.push(`anchor=${encodeURIComponent(anchorText)}`)
  }
  return `/polish?${parts.join('&')}`
}

/**
 * 目标岗位入口：把岗位带进润色页的目标岗位输入框（只预填，不触发分析）。
 * 空岗位 / 只有空白时退回裸 `/polish`，避免生成 `?role=` 这种空参数。
 */
export function polishRoleHref(targetRole: string | null | undefined): string {
  const role = targetRole == null ? '' : targetRole.trim()
  return role === '' ? '/polish' : `/polish?role=${encodeURIComponent(role)}`
}
