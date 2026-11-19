import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { CoachAgentRun } from '../api/types'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { CoachTrace } from '../components/coach/CoachTrace'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { COACH_TOOL_LABELS } from '../lib/coachTools'
import { useAsync } from '../lib/useAsync'

/** 阶段文案与粗粒度进度：后端不推进度，按已用秒数分档，与其他 AI 页面口径一致。 */
const RUN_PHASES = ['规划工具计划', '执行只读工具', '反思材料缺口', '生成带引用结论']

function phaseOf(elapsed: number): number {
  if (elapsed < 8) return 0
  if (elapsed < 28) return 1
  if (elapsed < 38) return 2
  return 3
}

const EXAMPLES = [
  'SQL 索引这块怎么补？',
  '我现在离后端岗位还差什么？',
  '给我安排一组事务隔离级别的练习',
  '我有哪些项目经历可以讲？',
]

const CAPABILITIES = [
  { tool: 'read_shortfalls', desc: '读最近报告的薄弱点，先看现状' },
  { tool: 'search_tutorials', desc: '站内教程混合检索，找可学的小节' },
  { tool: 'search_questions', desc: '题库找可练的题，不带答案' },
  { tool: 'read_plan', desc: '读 7 天计划进度，接着上次继续' },
  { tool: 'read_leap_archive', desc: '读岗位差距、项目证据与表达素材' },
]

function shortTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '刚刚'
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  return `${month}-${day} ${hour}:${minute}`
}

function finalActions(run: CoachAgentRun): string[] {
  return run.steps.flatMap((step) =>
    step.kind === 'final' && Array.isArray(step.actions)
      ? step.actions.filter((item): item is string => typeof item === 'string')
      : [],
  )
}

/**
 * 讲席（r100 B4 / r137 UI）：教练 Agent 编排的展示面。
 *
 * 与太傅（对话式问答）分工不同：这里演示**显式编排**——一次提问被规划成工具计划、
 * 逐步执行、反思不足再补跑，最后只基于工具结果写结论。整条轨迹随回答一起呈现，
 * 可回放「它为什么这么答」。本轮只做展示层升级：API 契约、工具闭集与轨迹语义不动。
 */
export default function CoachPage() {
  const [question, setQuestion] = useState('')
  const [goal, setGoal] = useState('')
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [run, setRun] = useState<CoachAgentRun | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const history = useAsync((signal) => api.coachAgentRuns(20, signal), [])

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [running])

  const submit = async (): Promise<void> => {
    if (question.trim() === '' || running) return
    setRunning(true)
    setElapsed(0)
    setError('')
    try {
      const result = await api.coachAgentRun({ question: question.trim(), goal: goal.trim() })
      setRun(result)
      setSelectedId(result.id)
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
      setSelectedId(runId)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const actions = run === null ? [] : finalActions(run)

  return (
    <section className="sc-coach-page">
      <header className="sc-page-header">
        <p className="sc-coach-kicker">AGENT ORCHESTRATION</p>
        <h1 className="sc-page-title">讲席</h1>
        <p className="sc-page-sub">
          把一个问题规划成工具计划，读完材料再作答。整条轨迹会留档回放——看的不是「它说了什么」，而是「它凭什么这么说」。
        </p>
      </header>

      <div className="sc-coach-layout">
        <div className="sc-coach-main">
          <Card className="sc-coach-composer">
            <div className="sc-coach-section-head">
              <h2>给讲席一个问题</h2>
              <span className="sc-coach-meta">只读工具 · 单轮 ≤3 步 · 全场 ≤2 轮</span>
            </div>
            <textarea
              className="sc-coach-question"
              value={question}
              maxLength={200}
              rows={3}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                  event.preventDefault()
                  void submit()
                }
              }}
              placeholder="例如：SQL 索引这块怎么补？"
              aria-label="给教练 Agent 的提问"
            />
            <div className="sc-coach-compose-row">
              <input
                className="sc-search-input"
                type="text"
                value={goal}
                maxLength={120}
                onChange={(event) => setGoal(event.target.value)}
                placeholder="目标岗位 / 时间约束（可选）"
                aria-label="目标岗位"
                autoComplete="off"
              />
              <Button
                loading={running}
                disabled={question.trim() === ''}
                onClick={() => void submit()}
              >
                {running ? '编排中…' : '开始编排'}
              </Button>
            </div>
            <div className="sc-coach-examples">
              <span className="sc-coach-meta">试试：</span>
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  className="sc-coach-example"
                  disabled={running}
                  onClick={() => setQuestion(example)}
                >
                  {example}
                </button>
              ))}
            </div>
            <p className="sc-coach-note">Ctrl / ⌘ + Enter 也可以提交；提问与回放按账号隔离。</p>
          </Card>

          {running ? (
            <PhaseLoader title="教练正在编排" phases={RUN_PHASES} active={phaseOf(elapsed)} elapsedSec={elapsed} />
          ) : null}
          {error ? <InlineError message={error} /> : null}

          {run ? (
            <Card className="sc-coach-run-card">
              <div className="sc-coach-result-head">
                <div>
                  <p className="sc-coach-kicker">本次编排</p>
                  <h2>{run.question}</h2>
                </div>
                <span className="sc-coach-run-id">{run.id}</span>
              </div>
              <div className="sc-coach-result-meta">
                <span>目标：{run.goal || '未指定'}</span>
                <span>轨迹 {run.steps.length} 步</span>
                <span>引用 {run.citations.length} 条</span>
                {run.dropped_citations > 0 ? (
                  <span>丢弃越界引用 {run.dropped_citations} 条</span>
                ) : null}
                {run.created_at ? <span>{shortTime(run.created_at)}</span> : null}
              </div>

              <section className="sc-coach-answer">
                <h3>结论</h3>
                <p>{run.answer}</p>
              </section>

              {actions.length > 0 ? (
                <section className="sc-coach-run-actions">
                  <h3>行动清单</h3>
                  <ol>
                    {actions.map((action, index) => (
                      <li key={`${action}-${index}`}>{action}</li>
                    ))}
                  </ol>
                </section>
              ) : null}

              {run.citations.length > 0 ? (
                <section className="sc-coach-citations">
                  <h3>依据（只来自工具结果）</h3>
                  <ul>
                    {run.citations.map((citation) => (
                      <li key={citation.ref}>
                        <span className="sc-coach-trace-ref">{citation.ref}</span>
                        <Link to={citation.href}>{citation.title}</Link>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {run.notice ? <p className="sc-coach-note">{run.notice}</p> : null}

              <details className="sc-coach-trace-fold" open>
                <summary>完整审计轨迹（{run.steps.length} 步）</summary>
                <CoachTrace steps={run.steps} />
              </details>
            </Card>
          ) : (
            <Card className="sc-coach-empty">
              <p className="sc-coach-kicker">HOW IT WORKS</p>
              <h2>先问一个问题</h2>
              <p className="sc-coach-note">
                讲席不会直接凭印象作答：它先选工具、再读材料、发现不够就补一轮，最后只引用工具返回过的条目。
              </p>
              <ol className="sc-coach-empty-flow">
                <li>规划工具</li>
                <li>执行检索</li>
                <li>反思缺口</li>
                <li>带引用结论</li>
              </ol>
            </Card>
          )}
        </div>

        <aside className="sc-coach-rail">
          <Card className="sc-coach-capabilities">
            <p className="sc-coach-kicker">TOOL CATALOG</p>
            <h2>它能读什么</h2>
            <ul>
              {CAPABILITIES.map((item) => (
                <li key={item.tool}>
                  <span className="sc-coach-trace-tool">{COACH_TOOL_LABELS[item.tool]}</span>
                  <span>{item.desc}</span>
                </li>
              ))}
            </ul>
            <p className="sc-coach-note">
              全部只读，不改动简历、报告或计划；越界引用会被丢弃并如实计数。
            </p>
          </Card>

          <Card className="sc-coach-history">
            <div className="sc-coach-section-head">
              <div>
                <p className="sc-coach-kicker">REPLAY</p>
                <h2>编排历史</h2>
              </div>
              <span className="sc-coach-meta">最近 {history.data?.length ?? 0} 条</span>
            </div>
            {history.status === 'loading' && history.data === null ? (
              <p className="sc-coach-note">正在读取历史…</p>
            ) : null}
            {history.status === 'error' && history.error ? (
              <InlineError message={history.error.message} onRetry={history.reload} />
            ) : null}
            {history.data && history.data.length === 0 ? (
              <p className="sc-coach-note">还没有编排记录：提问一次就会自动留档。</p>
            ) : null}
            {history.data && history.data.length > 0 ? (
              <ul className="sc-coach-history-list">
                {history.data.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={`sc-coach-history-item${selectedId === item.id ? ' is-active' : ''}`}
                      onClick={() => void replay(item.id)}
                    >
                      <span className="sc-coach-history-question">{item.question}</span>
                      <span className="sc-coach-history-meta">
                        {shortTime(item.created_at)} · {item.steps.length} 步 · {item.citations.length} 引用
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </Card>
        </aside>
      </div>
    </section>
  )
}
