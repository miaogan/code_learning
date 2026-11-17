import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { CoachAgentRun, CoachPlanStep, CoachTraceStep } from '../api/types'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { useAsync } from '../lib/useAsync'

/** 工具名 → 中文标签（与后端 TOOL_CATALOG 对齐；未知工具原样显示）。 */
const TOOL_LABELS: Record<string, string> = {
  read_shortfalls: '薄弱点',
  search_tutorials: '教程检索',
  search_questions: '题库检索',
  read_plan: '计划进度',
}

const STEP_TAGS: Record<string, string> = {
  plan: '01 / 规划',
  tool: '02 / 执行',
  tool_skip: '02 / 跳过',
  reflect: '03 / 反思',
  final: '04 / 结论',
}

function asText(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function asSteps(value: unknown): CoachPlanStep[] {
  return Array.isArray(value) ? (value as CoachPlanStep[]) : []
}

function asItems(value: unknown): { ref: string; title: string; snippet: string; href: string }[] {
  return Array.isArray(value)
    ? (value as { ref: string; title: string; snippet: string; href: string }[])
    : []
}

/** 一条轨迹的渲染：按 kind 分派；未知 kind 只显示 tag，不猜内容。 */
function TraceStep({ step, index }: { step: CoachTraceStep; index: number }) {
  const tag = STEP_TAGS[step.kind] ?? step.kind
  if (step.kind === 'plan') {
    const steps = asSteps(step.steps)
    return (
      <div className="sc-card" style={{ marginBottom: 'var(--sp-3)' }}>
        <p>
          <b>{tag}</b> · 目标：{asText(step.goal) || '未指定'}
          {step.fallback === true ? '（规划失败，已用兜底计划）' : ''}
        </p>
        <ul>
          {steps.map((item, i) => (
            <li key={`${item.tool}-${i}`}>
              {TOOL_LABELS[item.tool] ?? item.tool}
              {item.reason ? `：${item.reason}` : ''}
            </li>
          ))}
        </ul>
      </div>
    )
  }
  if (step.kind === 'tool') {
    const items = asItems(step.items)
    return (
      <div className="sc-card" style={{ marginBottom: 'var(--sp-3)' }}>
        <p>
          <b>{tag}</b> · {asText(step.label, String(step.tool))}
          {step.ok === true ? '' : '（未返回可用材料）'} · {asText(step.summary)}
        </p>
        <ul>
          {items.map((item) => (
            <li key={item.ref}>
              <Link to={item.href}>{item.title}</Link>
              {item.snippet ? `：${item.snippet}` : ''}
            </li>
          ))}
        </ul>
      </div>
    )
  }
  if (step.kind === 'tool_skip') {
    return (
      <p key={index}>
        {tag} · {asText(step.reason, '重复调用已跳过')}
      </p>
    )
  }
  if (step.kind === 'reflect') {
    const missing = Array.isArray(step.missing) ? (step.missing as string[]) : []
    return (
      <div className="sc-card" style={{ marginBottom: 'var(--sp-3)' }}>
        <p>
          <b>{tag}</b> · {step.sufficient === true ? '材料足够' : '材料不足'}
          {missing.length > 0 ? `，缺：${missing.join('；')}` : ''}
          {step.exhausted === true ? '（已达执行轮次上限）' : ''}
        </p>
      </div>
    )
  }
  if (step.kind === 'final') {
    const actions = Array.isArray(step.actions) ? (step.actions as string[]) : []
    return (
      <div className="sc-card" style={{ marginBottom: 'var(--sp-3)' }}>
        <p>
          <b>{tag}</b>
          {typeof step.dropped_citations === 'number' && step.dropped_citations > 0
            ? ` · 丢弃越界引用 ${step.dropped_citations} 条`
            : ''}
        </p>
        {actions.length > 0 ? (
          <ul>
            {actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        ) : null}
      </div>
    )
  }
  return <p>{tag}</p>
}

/**
 * 讲席（r100 B4）：教练 Agent 编排的展示面。
 *
 * 与太傅（对话式问答）分工不同：这里演示**显式编排**——一次提问被规划成工具计划、
 * 逐步执行、反思不足再补跑，最后只基于工具结果写结论；整条轨迹（plan / tool /
 * reflect / final）随回答一起呈现，可回放「它为什么这么答」。
 */
export default function CoachPage() {
  const [question, setQuestion] = useState('')
  const [goal, setGoal] = useState('')
  const [running, setRunning] = useState(false)
  const [run, setRun] = useState<CoachAgentRun | null>(null)
  const [error, setError] = useState('')
  const history = useAsync((signal) => api.coachAgentRuns(20, signal), [])

  const submit = async (): Promise<void> => {
    if (question.trim() === '' || running) return
    setRunning(true)
    setError('')
    try {
      const result = await api.coachAgentRun({ question: question.trim(), goal: goal.trim() })
      setRun(result)
      void history.reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  const replay = async (runId: string): Promise<void> => {
    setError('')
    try {
      setRun(await api.coachAgentRunDetail(runId))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">讲席</h1>
        <p className="sc-page-sub">
          教练 Agent：把一个问题规划成工具计划（薄弱点 / 教程检索 / 题库检索 / 计划进度），
          执行后反思材料是否足够、不足再补一轮，最后只基于工具结果作答。整条轨迹可回放。
        </p>
      </header>

      <div className="sc-search-bar">
        <input
          className="sc-search-input"
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：SQL 索引这块怎么补？"
          aria-label="给教练 Agent 的提问"
          autoComplete="off"
        />
        <input
          className="sc-search-input"
          type="text"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="目标岗位（可选，例如：后端 / AI 工程）"
          aria-label="目标岗位"
          autoComplete="off"
        />
        <button type="button" disabled={running || question.trim() === ''} onClick={() => void submit()}>
          {running ? '编排中…' : '让教练编排'}
        </button>
      </div>

      {running ? (
        <PhaseLoader
          title="教练正在编排"
          phases={['规划工具计划', '执行检索与读档', '反思材料是否足够', '生成带引用的结论']}
          active={1}
        />
      ) : null}
      {error ? <InlineError message={error} /> : null}

      {run ? (
        <>
          <h2>本次编排 · {run.question}</h2>
          <p>
            目标 {run.goal || '未指定'} · 轨迹 {run.steps.length} 步 · 引用 {run.citations.length} 条
            {run.dropped_citations > 0 ? ` · 丢弃越界引用 ${run.dropped_citations} 条` : ''}
            {run.created_at ? ` · ${run.created_at}` : ''}
          </p>
          {run.steps.map((step, index) => (
            <TraceStep key={`${step.kind}-${index}`} step={step} index={index} />
          ))}
          <h2>结论</h2>
          <p>{run.answer}</p>
          {run.citations.length > 0 ? (
            <>
              <h2>引用（只来自工具结果）</h2>
              <ul>
                {run.citations.map((citation) => (
                  <li key={citation.ref}>
                    <span>[{citation.ref}] </span>
                    <Link to={citation.href}>{citation.title}</Link>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {run.notice ? <p>{run.notice}</p> : null}
        </>
      ) : null}

      <h2>编排历史</h2>
      {history.status === 'loading' && history.data === null ? (
        <PhaseLoader title="正在读取历史" phases={['按时间倒序整理']} active={0} />
      ) : null}
      {history.status === 'error' && history.error ? (
        <InlineError message={history.error.message} onRetry={history.reload} />
      ) : null}
      {history.data && history.data.length === 0 ? (
        <p>还没有编排记录：在上面提问一次，轨迹会自动留档。</p>
      ) : null}
      {history.data && history.data.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>问题</th>
              <th>轨迹</th>
              <th>引用</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {history.data.map((item) => (
              <tr key={item.id}>
                <td>{item.created_at}</td>
                <td>{item.question}</td>
                <td>{item.steps.length} 步</td>
                <td>{item.citations.length} 条</td>
                <td>
                  <button type="button" onClick={() => void replay(item.id)}>
                    回放
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}
