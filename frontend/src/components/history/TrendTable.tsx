import { useEffect, useState } from 'react'
import type { RunKind, RunSummary } from '../../api/types'
import { formatScore } from '../../lib/format'
import { settingsLine } from '../interview/chatModel'
import { Chip } from '../ui/Chip'

export interface TrendTableProps {
  /**
   * 已由服务端按 `created_at` 倒序返回（`history.py` 是唯一排序口径），
   * 组件内**不再二次排序**，也**不做二次统计**（分数与短板数都取后端投影）。
   */
  rows: RunSummary[]
}

const KIND_LABEL: Record<RunKind, string> = { interview: '模拟面试', exam: '模拟笔试' }
/** 分数量纲：面试 = 均分（/10），笔试 = 总分（/100），因此两者永不互相比较。 */
const KIND_UNIT: Record<RunKind, string> = { interview: '/10', exam: '/100' }

const NO_COMPARE = '暂无对比'
const FLAT = '持平'
const DASH = '—'
/** 与 DESIGN §2.6「<640px 转卡片堆叠」同一断点。 */
const NARROW_QUERY = '(max-width: 640px)'

/** 服务端存的是 UTC ISO8601（`repository._now()`），展示按本机时区到分钟；解析失败原样回显。 */
function formatWhen(createdAt: string): string {
  const date = new Date(createdAt)
  if (Number.isNaN(date.getTime())) return createdAt
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 数值口径：整数不带 `.0`，否则保留 1 位（与 `format.ts` / `markdown.py` 同一规则）。 */
function trimmed(value: number): string {
  const rounded = Math.round(value * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

/**
 * 分数列。面试均分是 0–10，沿用 `format.ts` 的单一格式化入口；
 * 笔试总分是 0–100，`formatScore` 会把 >10 的值 clamp 成 10，故这里按同一规则独立渲染。
 */
function scoreText(kind: RunKind, score: number | null): string {
  if (score === null || !Number.isFinite(score)) return DASH
  const body = kind === 'interview' ? formatScore(score) : trimmed(score)
  return `${body} ${KIND_UNIT[kind]}`
}

/**
 * 历史行「本场设定」文本（AC-11）：面试行的设定由服务端投影 `RunSummary.interview_settings` 给出，
 * 旧记录（`null`）同字号同色显示「未记录设定」；笔试卷没有「本场设定」概念，返回 `null` 整行不渲染。
 * 文本一律经 `settingsLine`（唯一格式化入口），禁止在页面/组件里另拼一份，否则会出现
 * 「未记录设定 / undefined」三处漂移（TECHNICAL §重复风险-1）。
 */
export function settingsTextOf(row: RunSummary): string | null {
  if (row.kind !== 'interview') return null
  return settingsLine(row.interview_settings)
}

type DeltaTone = 'up' | 'down' | 'flat' | 'none'

interface DeltaView {
  text: string
  tone: DeltaTone
}

/**
 * 变化列：只与**同类型**的上一次比（面试对面试、笔试对笔试）。
 * 列表已是时间倒序，所以「上一次」= 本行之后第一条同类型记录；找不到即「暂无对比」。
 */
function deltaOf(rows: RunSummary[], index: number): DeltaView {
  const current = rows[index]
  const previous = rows.slice(index + 1).find((row) => row.kind === current.kind)
  if (previous === undefined) return { text: NO_COMPARE, tone: 'none' }
  if (current.score === null || previous.score === null) return { text: DASH, tone: 'none' }

  const diff = Math.round((current.score - previous.score) * 10) / 10
  if (diff === 0) return { text: FLAT, tone: 'flat' }
  const magnitude = trimmed(Math.abs(diff))
  return diff > 0
    ? { text: `↑ +${magnitude}`, tone: 'up' }
    : { text: `↓ −${magnitude}`, tone: 'down' }
}

/** 箭头 + 数字同时出现，颜色只是附加通道（DESIGN §2.6：不只颜色）。 */
function Delta({ delta }: { delta: DeltaView }) {
  if (delta.tone === 'up') return <span className="sc-delta-up">{delta.text}</span>
  if (delta.tone === 'down') return <span className="sc-delta-down">{delta.text}</span>
  return <span>{delta.text}</span>
}

/** 窄屏由 JS 判断：堆叠布局所需的媒体查询属 base.css（本次任务不改），故用 matchMedia 分支渲染。 */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(NARROW_QUERY).matches
  })

  useEffect(() => {
    const media = window.matchMedia(NARROW_QUERY)
    const onChange = (event: MediaQueryListEvent): void => setNarrow(event.matches)
    setNarrow(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  return narrow
}

export function TrendTable({ rows }: TrendTableProps) {
  const narrow = useNarrow()

  if (rows.length === 0) return null

  // 窄屏：每张卡 = 日期（含类型）+ 分数 / 短板 / 变化三行（DESIGN §2.6）。
  // 容器复用 .sc-grid-2：它在 <1024 已是单列 + gap，正好是堆叠所需，避免新增 CSS 尺寸。
  if (narrow) {
    return (
      <div className="sc-grid-2">
        {rows.map((row, index) => {
          const delta = deltaOf(rows, index)
          const shortfalls =
            row.shortfall_count === null ? DASH : `${row.shortfall_count} 条`
          const settings = settingsTextOf(row)
          return (
            <div className="sc-card" key={row.id}>
              <div className="sc-meta-line">
                <Chip label={KIND_LABEL[row.kind]} tone="direction" />
                <span className="sc-mono">{formatWhen(row.created_at)}</span>
              </div>
              {settings === null ? null : <p className="sc-td-settings">{settings}</p>}
              <p className="sc-meta-line">
                分数 <span className="sc-mono">{scoreText(row.kind, row.score)}</span>
              </p>
              <p className="sc-meta-line">
                短板 <span className="sc-mono">{shortfalls}</span>
              </p>
              <p className="sc-meta-line">
                对比 <Delta delta={delta} />
              </p>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <table className="sc-trend-table" aria-label="最近测评成绩趋势">
      <thead>
        <tr>
          <th scope="col">类型</th>
          <th scope="col">时间</th>
          <th scope="col">分数</th>
          <th scope="col">短板条数</th>
          <th scope="col">对比上次同类</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => {
          const delta = deltaOf(rows, index)
          const settings = settingsTextOf(row)
          return (
            <tr key={row.id}>
              <td>
                <div className="sc-td-kind">
                  <Chip label={KIND_LABEL[row.kind]} tone="direction" />
                  {settings === null ? null : <span className="sc-td-settings">{settings}</span>}
                </div>
              </td>
              <td className="sc-mono">{formatWhen(row.created_at)}</td>
              <td className="sc-mono">{scoreText(row.kind, row.score)}</td>
              <td className="sc-mono">{row.shortfall_count === null ? DASH : row.shortfall_count}</td>
              <td>
                <Delta delta={delta} />
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
