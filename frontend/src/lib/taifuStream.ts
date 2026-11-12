/**
 * r83 把 useChat 的 `parts` 翻译成界面模型。
 *
 * 组件只负责布局，所有判断（哪一段是正文、工具卡什么状态、引用在哪）都在这里：
 * 纯函数、无 React、无网络，可以直接用 vitest 钉住。
 */

import type { TaifuCitation } from '../api/types'

/** 工具名 → 中文短名。未知工具退回英文名，不猜含义。 */
const TOOL_LABELS: Record<string, string> = {
  read_weakness_detail: '薄弱明细',
  read_question_detail: '错题明细',
  read_resume_anchor: '简历原句',
  compare_reports: '报告对比',
  remember: '长期记忆',
}

export interface TextView {
  kind: 'text'
  key: string
  text: string
}

export interface ToolView {
  kind: 'tool'
  key: string
  name: string
  label: string
  /** `running` = 还在读；`done` = 有了结果（含「没读到」）。 */
  state: 'running' | 'done'
  ok: boolean
  summary: string
  args: Record<string, string>
}

export interface MetaView {
  kind: 'meta'
  key: string
  materials: number
  memoriesUsed: number
}

export interface CitationsView {
  kind: 'citations'
  key: string
  items: TaifuCitation[]
}

export type ViewPart = TextView | ToolView | MetaView | CitationsView

interface RawPart {
  type?: unknown
  text?: unknown
  toolCallId?: unknown
  state?: unknown
  input?: unknown
  output?: unknown
  data?: unknown
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {}
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function argumentsOf(input: unknown): Record<string, string> {
  const args = asRecord(asRecord(input).arguments)
  const kept: Record<string, string> = {}
  Object.entries(args).forEach(([key, value]) => {
    if (typeof value === 'string' && value) kept[key] = value
  })
  return kept
}

/**
 * 一段 `parts` → 视图列表。
 *
 * 不认识的部分（`reasoning`、`step-start`、`data-capped` 等）一律跳过：
 * 协议会随 ai-sdk 版本增加新 part，漏一个不该让整个面板白屏。
 */
export function partsToView(parts: readonly unknown[]): ViewPart[] {
  const view: ViewPart[] = []
  parts.forEach((raw, index) => {
    const part = asRecord(raw) as RawPart
    const type = asText(part.type)
    if (!type) return
    const key = `${type}-${index}`
    if (type === 'text') {
      const text = asText(part.text)
      if (text) view.push({ kind: 'text', key, text })
      return
    }
    if (type.startsWith('tool-')) {
      const name = type.slice('tool-'.length)
      const state = asText(part.state)
      const input = asRecord(part.input)
      const output = asRecord(part.output)
      const done = state === 'output-available' || state === 'output-error'
      view.push({
        kind: 'tool',
        key,
        name,
        // 结果里的标签更具体（带分组名 / 题面），拿不到才退回工具名。
        label: asText(output.label) || asText(input.label) || TOOL_LABELS[name] || name,
        state: done ? 'done' : 'running',
        ok: output.ok !== false,
        summary: done ? asText(output.summary) : '',
        args: argumentsOf(input),
      })
      return
    }
    if (type === 'data-meta') {
      const data = asRecord(part.data)
      view.push({
        kind: 'meta',
        key,
        materials: Number(data.materials) || 0,
        memoriesUsed: Number(data.memoriesUsed) || 0,
      })
      return
    }
    if (type === 'data-citations') {
      const items = asRecord(part.data).items
      if (Array.isArray(items) && items.length > 0) {
        view.push({ kind: 'citations', key, items: items as TaifuCitation[] })
      }
    }
  })
  return view
}

/** 一条消息的正文（复制、发问都只要这个）：把所有 text part 拼起来。 */
export function textOf(parts: readonly unknown[]): string {
  return parts
    .map((raw) => asRecord(raw))
    .filter((part) => part.type === 'text')
    .map((part) => asText(part.text))
    .join('')
}

/** 本轮的结束语（空档案 / 没生成出来时是唯一可见内容）。 */
export function noticeOf(parts: readonly unknown[]): string {
  for (const raw of parts) {
    const part = asRecord(raw)
    if (part.type === 'data-done') return asText(asRecord(part.data).notice)
  }
  return ''
}

/** 是否撞到了取料轮次上限：撞到了就如实说明，别让用户以为「就这些」。 */
export function cappedOf(parts: readonly unknown[]): boolean {
  return parts.some((raw) => asRecord(raw).type === 'data-capped')
}

/** 工具卡上显示的入参：只列有值的，避免「question_id：—」这种空行。 */
export function argsLine(args: Record<string, string>): string {
  return Object.entries(args)
    .map(([key, value]) => `${key}: ${value}`)
    .join(' · ')
}
