import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { ExamResult, ExamRun } from '../api/types'
import { ExamQuestionCard } from '../components/exam/ExamQuestionCard'
import { ExamResultPanel } from '../components/exam/ExamResultPanel'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Chip } from '../components/ui/Chip'
import { ConfirmModal } from '../components/ui/ConfirmModal'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { RingProgress } from '../components/ui/RingProgress'
import { filteredNotice, proficiencyRuleHint } from '../lib/examNotice'
import { formatElapsed } from '../lib/format'
import { useAsync } from '../lib/useAsync'

/** 卷面下限（AC-4：总数 ≥10、客观 ≥8），用于兜底拦截题型异常，不作为正常路径判断。 */
const MIN_QUESTIONS = 10
const MIN_OBJECTIVE = 8
/** 计时环显示上限（与 format.ts 的 99:59 上限一致）。 */
const TIMER_DISPLAY_MAX_S = 99 * 60 + 59
const CREATE_PHASES = ['读取画像方向', '按方向选题组卷', '校验客观题 ≥8 道']

type Stage = 'idle' | 'creating' | 'running' | 'submitting' | 'submitted'
type View = 'gate' | 'empty' | 'error' | Stage

function isAnswered(value: string[] | string | undefined): boolean {
  if (value === undefined) return false
  if (Array.isArray(value)) return value.length > 0
  return value.trim() !== ''
}

/**
 * 模拟笔试（AC-4）：出卷 → 计时作答（三种题型）→ 提交判分 → 结果面板 + 逐题复核。
 * 判分完全在服务端本地完成（不调 AI），所以展示层不做任何分数推算：
 * 总分 / 用时 / 客观题数 / 逐题对错一律以 `POST /api/exams/{run_id}/submit` 的响应为唯一真值。
 */
export default function ExamPage() {
  const profileAsync = useAsync((signal) => api.latestProfile(signal), [])
  const { pathname } = useLocation()
  const navigate = useNavigate()

  const [stage, setStage] = useState<Stage>('idle')
  const [run, setRun] = useState<ExamRun | null>(null)
  const [answers, setAnswers] = useState<Record<string, string[] | string>>({})
  const [result, setResult] = useState<ExamResult | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pendingLeave, setPendingLeave] = useState<string | null>(null)
  const [createElapsed, setCreateElapsed] = useState(0)
  const [runElapsed, setRunElapsed] = useState(0)

  const attemptRef = useRef(0)
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  const profile = profileAsync.data

  // 门禁：画像请求三态直接决定空态 / 错误态（与面试页同一套约定）。
  const gateView: 'gate' | 'empty' | 'error' | 'idle' =
    profileAsync.status === 'success'
      ? 'idle'
      : profileAsync.status === 'error'
        ? profileAsync.error?.status === 404
          ? 'empty'
          : 'error'
        : 'gate'
  const view: View = stage === 'idle' ? gateView : stage

  // 组卷等待：阶段文案随秒数步进（<3s → 0，<7s → 1，之后 → 2）。
  useEffect(() => {
    if (stage !== 'creating') return
    const timer = window.setInterval(() => setCreateElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [stage])

  // 本场正计时：进入 running 起表，提交中 / 已提交即停表（用时以服务端 elapsed_s 为准）。
  useEffect(() => {
    if (stage !== 'running') return
    const timer = window.setInterval(() => setRunElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [stage])

  const total = run ? run.questions.length : 0
  const objectiveTotal = run ? run.questions.filter((item) => item.kind !== 'text').length : 0
  const answeredCount = run
    ? run.questions.filter((item) => isAnswered(answers[item.id])).length
    : 0
  const submitting = stage === 'submitting'
  const createPhase = createElapsed < 3 ? 0 : createElapsed < 7 ? 1 : 2
  const timerLabel = submitting ? '判分中' : formatElapsed(Math.min(runElapsed, TIMER_DISPLAY_MAX_S))
  /**
   * AC-12：卷面首行的一行透明度文案。语义（净过滤数怎么算、0/NaN/负数怎么静默）
   * 只在 `lib/examNotice.ts` 一处定义，本页只取结果、**不再比较/改写**。
   */
  const notice = run ? filteredNotice(run.filtered_count) : null
  /** D-7 / D-9：与 notice 同一开关的规则说明（N=0 时同样不挂载）。 */
  const noticeHint = run ? proficiencyRuleHint(run.filtered_count) : null
  const hasAnyAnswer = answeredCount > 0

  // 作答中离开保护：刷新/关闭走浏览器原生提示，站内链接先确认 —— 作答只在本页 state，
  // 离开即丢失（面试有服务端会话可续答，笔试没有）。与润色页「生成中离开保护」同一套写法。
  useEffect(() => {
    if (stage !== 'running' || !hasAnyAnswer) {
      setPendingLeave(null)
      return
    }
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    const onClickCapture = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest('a[href]') : null
      if (!target) return
      const href = target.getAttribute('href')
      if (!href || href.startsWith('#') || /^[a-z]+:/i.test(href) || href === pathname) return
      event.preventDefault()
      event.stopPropagation()
      setPendingLeave(href)
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('click', onClickCapture, true)
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('click', onClickCapture, true)
    }
  }, [stage, hasAnyAnswer, pathname])

  const confirmLeave = () => {
    const href = pendingLeave
    setPendingLeave(null)
    if (href !== null) navigate(href)
  }

  const startExam = async () => {
    if (!profile) return
    const attempt = attemptRef.current + 1
    attemptRef.current = attempt
    setStage('creating')
    setCreateError(null)
    setSubmitError(null)
    setConfirmOpen(false)
    setCreateElapsed(0)
    try {
      const created = await api.createExam({ profile_id: profile.id })
      if (attemptRef.current !== attempt || !mountedRef.current) return
      const objective = created.questions.filter((item) => item.kind !== 'text').length
      if (created.questions.length < MIN_QUESTIONS || objective < MIN_OBJECTIVE) {
        setStage('idle')
        setCreateError(
          `题型异常：本次仅 ${created.questions.length} 题（客观 ${objective} 道，需 ${MIN_QUESTIONS} 题 / 客观 ${MIN_OBJECTIVE} 道），请重新生成试卷`,
        )
        return
      }
      setRun(created)
      setAnswers({})
      setResult(null)
      setRunElapsed(0)
      setStage('running')
    } catch (error) {
      if (attemptRef.current !== attempt || !mountedRef.current) return
      setStage('idle')
      setCreateError(error instanceof ApiError ? error.message : '组卷失败，请稍后重试')
    }
  }

  const cancelCreate = () => {
    attemptRef.current += 1
    setStage('idle')
  }

  const submitExam = async () => {
    if (!run || stage === 'submitting' || stage === 'submitted') return
    setConfirmOpen(false)
    setSubmitError(null)
    setStage('submitting')
    try {
      const graded = await api.submitExam(run.run_id, { answers })
      if (!mountedRef.current) return
      setResult(graded)
      setStage('submitted')
    } catch (error) {
      if (!mountedRef.current) return
      // 失败回到作答态：已选内容全部保留，只提示可重试（AC-4「失败不清空」）。
      setStage('running')
      setSubmitError(
        error instanceof ApiError
          ? error.message
          : '提交失败，本次判分未完成，你的作答已保留，可直接重试',
      )
    }
  }

  const requestSubmit = () => {
    if (!run || submitting) return
    if (answeredCount < total) {
      setConfirmOpen(true)
      return
    }
    void submitExam()
  }

  const setAnswer = (questionId: string, value: string[] | string) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }))
  }

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">模拟笔试</h1>
        <p className="sc-page-sub">
          客观题本地判分，提交后 10 秒内出总分、用时与逐题对错；失败不会清空你的选择
        </p>
      </header>

      {view === 'gate' ? (
        <PhaseLoader title="正在读取你的最新画像" phases={['读取画像']} active={0} />
      ) : null}

      {view === 'empty' ? (
        <EmptyState
          reason="笔试按画像方向组卷（≥10 题，其中客观题 ≥8 道自动判分）。先上传简历并确认画像，再来笔试。"
          actionLabel="上传简历"
          actionTo="/"
        />
      ) : null}

      {view === 'error' && profileAsync.error ? (
        <InlineError message={profileAsync.error.message} onRetry={profileAsync.reload} />
      ) : null}

      {view === 'idle' ? (
        <Card>
          <div className="sc-qcard-head">
            <Chip label="本卷规则" />
            <Chip label="总题 ≥10" tone="direction" />
            <Chip label="客观 ≥8" tone="direction" />
            <span className="sc-badge sc-badge--low">提交 10s 内出分</span>
          </div>
          <p className="sc-qcard-prompt">
            依据画像：目标岗位 {profile?.target_role ?? '未填写'} · 技能 {profile?.skills.length ?? 0} 项 · 项目{' '}
            {profile?.projects.length ?? 0} 个
          </p>
          <p className="sc-qcard-hint">
            单选 / 多选 / 简答三型混排，客观题多选题必须完全匹配才得分；简答不计入客观题数。计时从出卷后开始，仅记录用时。
          </p>
          {createError ? (
            <InlineError message={createError} onRetry={() => void startExam()} retryLabel="重新出卷" />
          ) : null}
          <div className="sc-btn-row">
            <Button onClick={() => void startExam()}>开始笔试</Button>
            <Link className="sc-btn sc-btn--secondary" to="/profile">
              先看看画像
            </Link>
          </div>
        </Card>
      ) : null}

      {view === 'creating' ? (
        <Card>
          <PhaseLoader
            title="正在依据画像组卷"
            phases={CREATE_PHASES}
            active={createPhase}
            elapsedSec={createElapsed}
          />
          <div className="sc-btn-row">
            <Button variant="ghost" onClick={cancelCreate}>
              取消
            </Button>
          </div>
        </Card>
      ) : null}

      {(view === 'running' || view === 'submitting') && run ? (
        <>
          {/* AC-12：`filtered_count = 0` / 字段缺失时 notice 为 null → 不挂载节点（零占位）。 */}
          {notice ? (
            <span className="sc-meta-line">
              <Chip label="熟练过滤" />
              {' '}
              <span>{notice}</span>
              {noticeHint ? <span>{`· ${noticeHint}`}</span> : null}
            </span>
          ) : null}

          <div className="sc-actions">
            <RingProgress
              size={64}
              stroke={6}
              value={runElapsed % 60}
              max={60}
              label={timerLabel}
              state={submitting ? 'indeterminate' : 'default'}
              ariaLabel={`本卷已用时 ${formatElapsed(Math.min(runElapsed, TIMER_DISPLAY_MAX_S))}`}
            />
            <span className="sc-meta-line">
              {`${total} 题 · 客观 ${objectiveTotal} · 已答 ${answeredCount} / ${total}`}
              {submitting ? ' · 判分中，10 秒内出分' : ''}
            </span>
          </div>

          <div className="sc-chips" aria-label="逐题作答进度">
            {run.questions.map((question, slot) => (
              <Chip
                key={question.id}
                label={`Q${slot + 1}`}
                tone={isAnswered(answers[question.id]) ? 'direction' : 'default'}
              />
            ))}
          </div>

          {confirmOpen ? (
            <Card>
              <p className="sc-qcard-prompt">
                {`还有 ${total - answeredCount} 题未答，仍要提交？`}
              </p>
              <p className="sc-qcard-hint">未作答的题会按错误计分；提交后本卷成绩固定，不能再改。</p>
              <div className="sc-btn-row">
                <Button onClick={() => void submitExam()} loading={submitting}>
                  确认提交
                </Button>
                <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
                  继续作答
                </Button>
              </div>
            </Card>
          ) : null}

          {submitError ? (
            <InlineError
              message={submitError}
              onRetry={() => void submitExam()}
              retryLabel="重试提交"
            />
          ) : null}

          {run.questions.map((question, slot) => (
            <ExamQuestionCard
              key={question.id}
              index={slot}
              question={question}
              value={answers[question.id] ?? (question.kind === 'text' ? '' : [])}
              onChange={(value) => setAnswer(question.id, value)}
              locked={submitting}
            />
          ))}

          <div className="sc-btn-row is-end">
            <span className="sc-meta-line">
              已答 {answeredCount} / {total}
            </span>
            <Button onClick={requestSubmit} loading={submitting} disabled={submitting}>
              提交试卷
            </Button>
          </div>
        </>
      ) : null}

      {view === 'submitted' && run && result ? (
        <>
          <ExamResultPanel result={result} questions={run.questions} />

          {/* D-8：复核时回看本卷的过滤事实（只复显事实，不回放规则说明，避免抢走 40px 总分的焦点）。 */}
          {notice ? (
            <span className="sc-meta-line">
              <Chip label="熟练过滤" />
              {' '}
              <span>{notice}</span>
            </span>
          ) : null}

          {run.questions.map((question, slot) => (
            <ExamQuestionCard
              key={question.id}
              index={slot}
              question={question}
              value={answers[question.id] ?? (question.kind === 'text' ? '' : [])}
              onChange={() => undefined}
              review={result.per_question.find((item) => item.question_id === question.id) ?? null}
            />
          ))}

          <div className="sc-btn-row">
            <Link
              className="sc-btn sc-btn--primary"
              to={`/report?run_ids=${encodeURIComponent(run.run_id)}`}
            >
              生成诊断报告
            </Link>
            <Button variant="secondary" onClick={() => void startExam()}>
              再出一套笔试
            </Button>
          </div>
        </>
      ) : null}

      <ConfirmModal
        open={pendingLeave !== null}
        title="离开会丢失本次作答"
        message={`已答 ${answeredCount} / ${total} 题。刷新或离开后，本卷的选择将无法恢复。`}
        confirmLabel="仍然离开"
        cancelLabel="留在本页"
        onConfirm={confirmLeave}
        onCancel={() => setPendingLeave(null)}
      />
    </section>
  )
}
