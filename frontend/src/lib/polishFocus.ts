import type { PolishSection, PolishSuggestion } from '../api/types'

/**
 * 报告页 → 润色页的定位契约（AC-5）的**唯一实现处**。
 *
 * 为什么要单独一个模块：定位逻辑（解析参数 / 匹配条目 / 未命中文案 / 段落中文名）如果散在
 * `PolishPage` 与 `SuggestionCard` 两处，vitest 就只能靠渲染整页来测，且两份段落名会漂移。
 * 这里全是纯函数，零 DOM、零网络，`src/test/polishFocus.test.ts` 直接调即可。
 *
 * 匹配口径（AC-5 只认逐字相等，反面目标 3「要点指向不存在的句子」的唯一防线）：
 * 先用 `anchor`（原文逐字切片）与 `original_text` 全等比较；只带 `focus` 时退化为用 `focus`
 * 比较；都不中才算未命中，此时**不做模糊匹配**，只降级为按 section 预筛。
 */

/** 与后端 `services/coach_copy.py::SECTION_LABEL` 逐字一致的段落中文名。 */
export const SECTION_LABEL: Record<PolishSection, string> = {
  project: '项目经历',
  experience: '工作经历',
  education: '教育背景',
  summary: '个人简介',
}

/** 命中条目时该卡的 DOM id（`SuggestionCard` 只在 `focused` 时挂上，全页唯一）。 */
export const FOCUS_ELEMENT_ID = 'sc-focus-target'

/** 进入页面但还没有建议列表时的灰字提示（不阻断、不自动调模型）。 */
export const FOCUS_PENDING_NOTICE = '分析完成后会自动定位到报告里指出的那一条'

const SECTION_KEYS: readonly string[] = ['project', 'experience', 'education', 'summary']

export interface FocusTarget {
  /** 定位键（当前语义即 `anchor_text`）。 */
  focus: string
  /** 预筛用段落；参数缺失或非法时为 `null`（不预筛）。 */
  section: PolishSection | null
  /** 逐字锚点；报告页只在 ≤120 字符时携带。 */
  anchor: string | null
}

function toSection(value: string | null): PolishSection | null {
  const text = (value ?? '').trim()
  return SECTION_KEYS.includes(text) ? (text as PolishSection) : null
}

/**
 * 解析 `/polish?focus=&section=&anchor=`。
 *
 * 无 `focus` → `null`（不是「定位到某条」的入口，页面行为完全不变）。
 * `section` 非法 → 该字段为 `null` 但仍返回目标：宁可少一层筛选，也不要因为一个坏参数
 * 把整次定位吞掉（用户点的是「去改这一条」，不该看到「什么都没发生」）。
 */
export function parseFocusParams(params: URLSearchParams): FocusTarget | null {
  const focus = (params.get('focus') ?? '').trim()
  if (focus === '') return null
  const anchor = (params.get('anchor') ?? '').trim()
  return { focus, section: toSection(params.get('section')), anchor: anchor === '' ? null : anchor }
}

/** 在建议列表里找 `anchor_text` 逐字相等的那一条；找不到返回 `null`（不模糊匹配）。 */
export function findFocusedSuggestion(
  suggestions: PolishSuggestion[],
  target: FocusTarget,
): PolishSuggestion | null {
  if (target.anchor !== null) {
    const hit = suggestions.find((item) => item.original_text === target.anchor)
    if (hit !== undefined) return hit
  }
  return suggestions.find((item) => item.original_text === target.focus) ?? null
}

/** 未命中时的顶部提示条文案（中文、含段落名，让用户知道列表为什么变短了）。 */
export function focusNotice(section: PolishSection | null): string {
  return section === null
    ? '未找到对应条目，已显示全部建议'
    : `未找到对应条目，已按「${SECTION_LABEL[section]}」筛选`
}
