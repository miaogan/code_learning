import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { InterviewQuestion, InterviewRun, ScoreResult } from '../api/types'
import { QuestionCard, QUESTION_KIND_LABEL } from '../components/interview/QuestionCard'
import { ScoreBadge, scoreRingState } from '../components/interview/ScoreBadge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Chip } from '../components/ui/Chip'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { RingProgress } from '../components/ui/RingProgress'
import { formatElapsed, formatScore } from '../lib/format'
import { useAsync } from '../lib/useAsync'

/** 页面阶段：intro 由画像请求派生，其余为用户推进后的确定状态。 */
type Stage = 'intro' | 'creating' | 'running' | 'done'
type View = 'gate' | 'empty' | 'error' | 'intro' | Stage

/** 出题阶段文案（DESIGN §0.6：AI 调用用三段式步进，禁止只有转圈）。 */
const CREATE_PHASES = ['读取画像要点', '按画像配比出题（技术 / 项目深挖）', '校验题量与去重']

/** 本题计时环显示上限 59:59（DESIGN §2.3）。 */
const TIMER_DISPLAY_MAX_S = 59 * 60 + 59

/** 逐题进度格：得分档上色 + 数字双通道（<4 红 / 4–7 黄 / >7 中性描边）。 */
function stripBadgeClass(score: ScoreResult): string {
  const state = scoreRingState(score.score)
  if (state === 'danger') return 'sc-badge sc-badge--high'
  if (state === 'warn') return 'sc-badge sc-badge--medium'
  return 'sc-badge sc-badge--low'
}

function averageOf(values: number[]): number {
  if (values.length === 0) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

/**
 * 模拟面试（AC-3）：逐题单屏、同卡出分、失败永不清空作答；
 * 最后一题出分后进入本场汇总（均分），再进诊断报告。
 */
export default function InterviewPage() {
  const createAbortRef = useRef<AbortController | null>(null)

  const profileAsync = useAsync((signal) => api.latestProfile(signal), [])

  const [stage, setStage] = useState<Stage>('intro')
  const [run, setRun] = useState<InterviewRun | null>(null)
  const [index, setIndex] = useState(0)
  const [answers, setAnswers] = useState<Partial<Record<string, string>>>({})
  const [scores, setScores] = useState<Partial<Record<string, ScoreResult>>>({})

  const [submitting, setSubmitting] = useState(false)
  const [scoreError, setScoreError] = useState<string | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)
  const [createElapsed, setCreateElapsed] = useState(0)
  const [answerElapsed, setAnswerElapsed] = useState(0)
  const [reviewing, setReviewing] = useState(false)

  const profile = profileAsync.data
  const total = run ? run.questions.length : 0
  const currentQuestion: InterviewQuestion | null = run ? (run.questions[index] ?? null) : null
  const currentScore: ScoreResult | null = currentQuestion ? (scores[currentQuestion.id] ?? null) : null

  // 门禁：画像请求三态直接决定空态 / 错误态，不额外引入 sync 副作用。
  const gateView: 'gate' | 'empty' | 'error' | 'intro' =
    profileAsync.status === 'success'
      ? 'intro'
      : profileAsync.status === 'error'
        ? profileAsync.error?.status === 404
          ? 'empty'
          : 'error'
        : 'gate'
  const view: View = stage === 'intro' ? gateView : stage

  // 出题等待：阶段文案随秒数步进（<2s → 0，<5s → 1，之后 → 2）。
  useEffect(() => {
    if (view !== 'creating') return
    const timer = window.setInterval(() => setCreateElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [view])

  // 本题正计时：提交中 / 已出分即停表（DESIGN §2.3 计时环含义）。
  useEffect(() => {
    if (view !== 'running' || currentScore !== null || submitting) return
    const timer = window.setInterval(() => setAnswerElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [view, index, currentScore, submitting])

  useEffect(() => {
    return () => {
      createAbortRef.current?.abort()
    }
  }, [])

  const startRun = async () => {
    if (!profile) return
    createAbortRef.current?.abort()
    const controller = new AbortController()
    createAbortRef.current = controller
    setCreateError(null)
    setCreateElapsed(0)
    setStage('creating')
    try {
      const result = await api.createInterview({ profile_id: profile.id })
      if (controller.signal.aborted) return
      if (result.questions.length === 0) {
        setCreateError('本次出题没有返回题目，请重试')
        setStage('intro')
        return
      }
      setRun(result)
      setAnswers({})
      setScores({})
      setIndex(0)
      setAnswerElapsed(0)
      setScoreError(null)
      setReviewing(false)
      setStage('running')
    } catch (err) {
      if (controller.signal.aborted) return
      setCreateError(err instanceof ApiError ? err.message : '出题失败，请重试')
      setStage('intro')
    }
  }

  const cancelCreate = () => {
    createAbortRef.current?.abort()
    setCreateElapsed(0)
    setStage('intro')
  }

  /** 单题评分：失败只报错，answers 原样保留 → textarea 不清空（AC-3）。 */
  const submitAnswer = async () => {
    if (!run || !currentQuestion || submitting) return
    const questionId = currentQuestion.id
    const text = (answers[questionId] ?? '').trim()
    if (text.length === 0) return

    setSubmitting(true)
    setScoreError(null)
    try {
      const result = await api.scoreAnswer(run.run_id, { question_id: questionId, answer: text })
      setScores((prev) => ({ ...prev, [questionId]: result }))
    } catch (err) {
      setScoreError(
        err instanceof ApiError
          ? `${err.message}（你的答案已保留，可直接重试）`
          : '评分失败，你的答案已保留，请重试',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const goNext = () => {
    if (!run) return
    if (index + 1 < run.questions.length) {
      setIndex(index + 1)
      setAnswerElapsed(0)
      setScoreError(null)
      return
    }
    setStage('done')
  }

  /** 重新作答：只清分数，保留原答案（DESIGN §2.3 评分态次按钮）。 */
  const reopenAnswer = () => {
    if (!currentQuestion) return
    const questionId = currentQuestion.id
    setScores((prev) => {
      const next = { ...prev }
      delete next[questionId]
      return next
    })
    setScoreError(null)
  }

  const answeredCount = run ? run.questions.filter((item) => scores[item.id]).length : 0
  const answeredScores = run
    ? run.questions
        .map((item) => scores[item.id]?.score)
        .filter((value): value is number => typeof value === 'number')
    : []
  const overallAvg = averageOf(answeredScores)
  const kindAvg = (kind: InterviewQuestion['kind']): number => {
    if (!run) return 0
    const values = run.questions
      .filter((item) => item.kind === kind)
      .map((item) => scores[item.id]?.score)
      .filter((value): value is number => typeof value === 'number')
    return averageOf(values)
  }

  const createPhase = createElapsed < 2 ? 0 : createElapsed < 5 ? 1 : 2
  const timerLabel = submitting ? '评分中' : formatElapsed(Math.min(answerElapsed, TIMER_DISPLAY_MAX_S))

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">模拟面试</h1>
        <p className="sc-page-sub">逐题作答、同卡出分：每题 0–10 分与一段点评；失败不会清空你的答案</p>
      </header>

      {view === 'gate' ? <PhaseLoader title="正在读取你的最新画像" phases={['读取画像']} active={0} /> : null}

      {view === 'empty' ? (
        <EmptyState
          reason="模拟面试会依据你的画像出题（技术题 ≥5 · 项目深挖 ≥3 · 进阶 ≤20%，逐题 0–10 分）。先上传简历并确认画像，再来测评。"
          actionLabel="上传简历"
          actionTo="/"
        />
      ) : null}

      {view === 'error' && profileAsync.error ? (
        <InlineError message={profileAsync.error.message} onRetry={profileAsync.reload} />
      ) : null}

      {view === 'intro' ? (
        <Card>
          <div className="sc-qcard-head">
            <Chip label="本场规则" />
            <Chip label="技术题 ≥5" tone="direction" />
            <Chip label="项目深挖 ≥3" tone="direction" />
            <span className="sc-badge sc-badge--medium">进阶 ≤20%</span>
          </div>
          <p className="sc-qcard-prompt">
            依据画像：目标岗位 {profile?.target_role ?? '未填写'} · 技能 {profile?.skills.length ?? 0} 项 · 项目{' '}
            {profile?.projects.length ?? 0} 个
          </p>
          <p className="sc-qcard-hint">
            逐题单屏作答，提交后当场出分；评分失败或超时时答案会保留在输入框，绝不丢失。
          </p>
          {createError ? (
            <InlineError message={createError} onRetry={() => void startRun()} retryLabel="重新出题" />
          ) : null}
          <div className="sc-btn-row">
            <Button onClick={() => void startRun()}>开始模拟面试</Button>
            <Link className="sc-btn sc-btn--secondary" to="/profile">
              先看看画像
            </Link>
          </div>
        </Card>
      ) : null}

      {view === 'creating' ? (
        <Card>
          <PhaseLoader title="正在依据画像出题" phases={CREATE_PHASES} active={createPhase} elapsedSec={createElapsed} />
          <div className="sc-btn-row">
            <Button variant="ghost" onClick={cancelCreate}>
              取消
            </Button>
          </div>
        </Card>
      ) : null}

      {view === 'running' && run && currentQuestion ? (
        <>
          <div className="sc-actions">
            <RingProgress
              size={64}
              stroke={6}
              value={answerElapsed % 60}
              max={60}
              label={timerLabel}
              state={submitting ? 'indeterminate' : 'default'}
              ariaLabel={`本题已用时 ${formatElapsed(Math.min(answerElapsed, TIMER_DISPLAY_MAX_S))}`}
            />
            <span className="sc-meta-line">
              第 {index + 1} / {total} 题 · 已答 {answeredCount} 题
              {currentScore ? ' · 本题已出分' : submitting ? ' · 正在评分' : ''}
            </span>
          </div>

          <div className="sc-chips" aria-label="逐题进度">
            {run.questions.map((item, slot) => {
              const slotScore = scores[item.id]
              return (
                <span
                  key={item.id}
                  className={slotScore ? stripBadgeClass(slotScore) : 'sc-badge sc-muted'}
                  aria-current={slot === index ? 'step' : undefined}
                >
                  Q{slot + 1}
                  {slotScore ? ` ${formatScore(slotScore.score)}` : ''}
                </span>
              )
            })}
          </div>

          <QuestionCard
            index={index}
            total={total}
            question={currentQuestion}
            answer={answers[currentQuestion.id] ?? ''}
            score={currentScore}
            submitting={submitting}
            errorMessage={scoreError ?? undefined}
            onAnswerChange={(value) => setAnswers((prev) => ({ ...prev, [currentQuestion.id]: value }))}
            onSubmit={() => void submitAnswer()}
            onRetry={() => void submitAnswer()}
          />

          {currentScore ? (
            <div className="sc-btn-row">
              <Button onClick={goNext}>{index + 1 < total ? '下一题' : '完成并查看汇总'}</Button>
              <Button variant="secondary" onClick={reopenAnswer}>
                重新作答（保留原答案）
              </Button>
            </div>
          ) : null}
        </>
      ) : null}

      {view === 'done' && run ? (
        <>
          <Card>
            <div className="sc-qcard-head">
              <Chip label="本场汇总" />
              <span className="sc-meta-line">
                已答 {answeredCount} / {total} 题
                {answeredCount < total ? `（还有 ${total - answeredCount} 题未作答）` : ' · 全部完成'}
              </span>
            </div>
            <div className="sc-score-side">
              <RingProgress
                size={56}
                stroke={5}
                value={overallAvg}
                max={10}
                label={formatScore(overallAvg)}
                state={scoreRingState(overallAvg)}
                ariaLabel={`本次面试均分 ${formatScore(overallAvg)} 分，满分 10 分`}
              />
              <p className="sc-mono">本场均分 {formatScore(overallAvg)} / 10</p>
              <p className="sc-score-comment">
                技术题 {formatScore(kindAvg('technical'))} · 项目深挖 {formatScore(kindAvg('project'))}
                {kindAvg('challenge') > 0 ? ` · 进阶 ${formatScore(kindAvg('challenge'))}` : ''}
              </p>
            </div>
            <p className="sc-meta-line">短板与课程由诊断报告统一给出，面试评分只是其中一类证据。</p>
            <div className="sc-btn-row">
              <Link className="sc-btn sc-btn--primary" to="/report">
                生成诊断报告
              </Link>
              <Button variant="secondary" onClick={() => setReviewing((value) => !value)}>
                {reviewing ? '收起本次作答' : '回看本次作答'}
              </Button>
            </div>
          </Card>

          {reviewing
            ? run.questions.map((item, slot) => {
                const slotScore = scores[item.id]
                return (
                  <Card key={item.id} className="sc-qcard">
                    <div className="sc-qcard-head">
                      <Chip label={`Q${slot + 1}`} />
                      <Chip label={QUESTION_KIND_LABEL[item.kind]} tone="direction" />
                      <span className="sc-meta-line">
                        {slotScore ? `${formatScore(slotScore.score)} / 10` : '未作答'}
                      </span>
                    </div>
                    <h2 className="sc-qcard-prompt">{item.prompt}</h2>
                    <p className="sc-qcard-hint">{(answers[item.id] ?? '').trim() || '（本题未作答）'}</p>
                    {slotScore ? <ScoreBadge score={slotScore.score} comment={slotScore.comment} /> : null}
                  </Card>
                )
              })
            : null}
        </>
      ) : null}
    </section>
  )
}
