import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { CoachPlanStep, CoachTraceStep } from '../../api/types'
import { COACH_TOOL_LABELS } from '../../lib/coachTools'

const STEP_META: Record<string, { order: string; label: string }> = {
  plan: { order: '01', label: '规划' },
  tool: { order: '02', label: '执行' },
  tool_skip: { order: '02', label: '跳过' },
  reflect: { order: '03', label: '反思' },
  final: { order: '04', label: '结论' },
}

interface TraceItem {
  ref: string
  title: string
  snippet: string
  href: string
}

function asText(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function asSteps(value: unknown): CoachPlanStep[] {
  return Array.isArray(value) ? (value as CoachPlanStep[]) : []
}

function asItems(value: unknown): TraceItem[] {
  return Array.isArray(value) ? (value as TraceItem[]) : []
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function argsText(value: unknown): string | null {
  if (typeof value !== 'object' || value === null) return null
  const parts = Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => typeof item === 'string' && item.trim() !== '')
    .map(([key, item]) => `${key}=${String(item).trim()}`)
  return parts.length > 0 ? parts.join(' · ') : null
}

function toolLabel(name: string): string {
  return COACH_TOOL_LABELS[name] ?? (name || '工具')
}

function TraceNode({ step }: { step: CoachTraceStep }) {
  const kind = step.kind
  const meta = STEP_META[kind] ?? { order: '··', label: asText(kind, '步骤') }

  let body: ReactNode = <p className="sc-coach-trace-line is-muted">该步骤无更多细节</p>
  let badge: { text: string; tone?: string } | null = null

  if (kind === 'plan') {
    const steps = asSteps(step.steps)
    badge = step.fallback === true ? { text: '兜底计划', tone: 'warn' } : null
    body = (
      <>
        <p className="sc-coach-trace-line">目标：{asText(step.goal, '未指定')}</p>
        {steps.length > 0 ? (
          <ol className="sc-coach-trace-plan">
            {steps.map((item, itemIndex) => (
              <li key={`${item.tool}-${itemIndex}`}>
                <span className="sc-coach-trace-tool">{toolLabel(item.tool)}</span>
                {item.reason ? <span>{item.reason}</span> : null}
              </li>
            ))}
          </ol>
        ) : null}
      </>
    )
  } else if (kind === 'tool') {
    const items = asItems(step.items)
    const args = argsText(step.args)
    badge = step.ok === true ? null : { text: '未返回材料', tone: 'muted' }
    body = (
      <>
        <p className="sc-coach-trace-line">
          <span className="sc-coach-trace-tool">{toolLabel(asText(step.tool))}</span>
          <span>{asText(step.summary)}</span>
        </p>
        {args ? <p className="sc-coach-trace-args">参数：{args}</p> : null}
        {items.length > 0 ? (
          <ul className="sc-coach-trace-items">
            {items.map((item, itemIndex) => (
              <li key={`${item.ref}-${itemIndex}`}>
                <span className="sc-coach-trace-ref">{item.ref}</span>
                <Link to={item.href}>{item.title}</Link>
                {item.snippet ? <span className="sc-coach-trace-snippet">{item.snippet}</span> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </>
    )
  } else if (kind === 'tool_skip') {
    body = <p className="sc-coach-trace-line is-muted">{asText(step.reason, '重复调用已跳过')}</p>
  } else if (kind === 'reflect') {
    const missing = asStrings(step.missing)
    const extra = asSteps(step.extra_steps)
    badge = {
      text: step.sufficient === true ? '材料足够' : '材料不足',
      tone: step.sufficient === true ? 'ok' : 'warn',
    }
    body = (
      <>
        {missing.length > 0 ? (
          <p className="sc-coach-trace-line">缺口：{missing.join('；')}</p>
        ) : null}
        {extra.length > 0 ? (
          <p className="sc-coach-trace-line">
            补跑：{extra.map((item) => toolLabel(item.tool)).join('、')}
          </p>
        ) : null}
        {step.exhausted === true ? (
          <p className="sc-coach-trace-line is-muted">已达执行轮次上限，直接收敛到结论</p>
        ) : null}
      </>
    )
  } else if (kind === 'final') {
    const actions = asStrings(step.actions)
    const dropped = typeof step.dropped_citations === 'number' ? step.dropped_citations : 0
    badge = dropped > 0 ? { text: `丢弃越界引用 ${dropped} 条`, tone: 'warn' } : null
    body =
      actions.length > 0 ? (
        <ol className="sc-coach-trace-actions">
          {actions.map((action, itemIndex) => (
            <li key={`${action}-${itemIndex}`}>{action}</li>
          ))}
        </ol>
      ) : null
  }

  return (
    <li className={`sc-coach-trace-node is-${kind}`}>
      <span className="sc-coach-trace-order" aria-hidden="true">
        {meta.order}
      </span>
      <div className="sc-coach-trace-content">
        <div className="sc-coach-trace-head">
          <span className="sc-coach-trace-label">{meta.label}</span>
          {badge ? (
            <span className={`sc-coach-trace-badge${badge.tone ? ` is-${badge.tone}` : ''}`}>
              {badge.text}
            </span>
          ) : null}
        </div>
        {body}
      </div>
    </li>
  )
}

/**
 * 讲席审计轨迹时间线：plan / tool / tool_skip / reflect / final 按原顺序渲染。
 * 未知 kind 只显示标签与兜底文案，不猜字段含义——与后端「轨迹即审计」的口径一致。
 */
export function CoachTrace({ steps }: { steps: CoachTraceStep[] }) {
  if (steps.length === 0) {
    return <p className="sc-coach-trace-empty">这次编排没有留下轨迹。</p>
  }
  return (
    <ol className="sc-coach-trace-list">
      {steps.map((step, index) => (
        <TraceNode key={`${step.kind}-${index}`} step={step} />
      ))}
    </ol>
  )
}
