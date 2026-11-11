import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { ExamResult, ExamRun } from '../api/types'
import { ExamQuestionCard } from '../components/exam/ExamQuestionCard'
import { ExamResultPanel } from '../components/exam/ExamResultPanel'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Chip } from '../components/ui/Chip'
import { MultiChipRow, type ChipOption } from '../components/ui/ChipRow'
import { ConfirmModal } from '../components/ui/ConfirmModal'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { ResumeGate } from '../components/ui/ResumeGate'
import { RingProgress } from '../components/ui/RingProgress'
import { Select } from '../components/ui/Select'
import { backfillNotice, filteredNotice, proficiencyRuleHint, subDirectionNotice } from '../lib/examNotice'
import { formatElapsed, formatWhen } from '../lib/format'
import { clearExamDraft, readExamDraft, writeExamDraft } from '../lib/examDraft'
import { DIRECTIONS, SUBDIRECTIONS } from '../lib/questionDirections'
import { useAsync } from '../lib/useAsync'
import { setFlow } from '../state/flow'
import { useAuth } from '../state/auth'

/** 卷面下限（AC-4：总数 ≥10、客观 ≥8），用于兜底拦截题型异常，不作为正常路径判断。 */
const MIN_QUESTIONS = 10
const MIN_OBJECTIVE = 8
/** 计时环显示上限（与 format.ts 的 99:59 上限一致）。 */
const TIMER_DISPLAY_MAX_S = 99 * 60 + 59
const CREATE_PHASES = ['读取画像方向', '按方向选题组卷', '校验客观题 ≥8 道']

type Stage = 'idle' | 'creating' | 'running' | 'submitting' | 'submitted'
type View = 'gate' | 'empty' | 'error' | Stage

/** 方向闭集与二级方向闭集：统一从 lib/questionDirections 派生（与后端 rules 逐字一致）。
 * 多选的「不限」哨兵统一用空串：空数组 / 勾满具体项都会被 `MultiChipRow` 折叠成 `['']`。 */
const DIRECTION_OPTIONS: ChipOption<string>[] = [
  { value: '', label: '按画像智能组卷' },
  ...DIRECTIONS.map((direction) => ({ value: direction, label: direction })),
]
const DIFFICULTY_OPTIONS: ChipOption<string>[] = [
  { value: '', label: '不限难度' },
  { value: 'basic', label: '基础（basic）' },
  { value: 'intermediate', label: '进阶（intermediate）' },
  { value: 'challenge', label: '挑战（challenge）' },
]
const QUESTION_COUNT_OPTIONS: { value: number | null; label: string }[] = [
  { value: null, label: '默认 10–12' },
  { value: 12, label: '12 题' },
  { value: 15, label: '15 题' },
  { value: 20, label: '20 题' },
]

function isAnswered(value: string[] | string | undefined): boolean {
  if (value === undefined) return false
  if (Array.isArray(value)) return value.length > 0
  return value.trim() !== ''
}

/**
 * 科考（AC-4）：出卷 → 计时作答（三种题型）→ 提交判分 → 结果面板 + 逐题复核。
 * 判分完全在服务端本地完成（不调 AI），所以展示层不做任何分数推算：
 * 总分 / 用时 / 客观题数 / 逐题对错一律以 `POST /api/exams/{run_id}/submit` 的响应为唯一真值。
 */
export default function ExamPage() {
  const profileAsync = useAsync((signal) => api.latestProfile(signal), [])
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { me } = useAuth()
  const userId = me?.id ?? null
  // 初始化是纯读：StrictMode 两次执行不会消费或清掉同一份草稿。
  const [restored] = useState(() => readExamDraft(userId))
  const restoredDraft = restored.status === 'ok' ? restored.draft : null

  const [stage, setStage] = useState<Stage>(restoredDraft === null ? 'idle' : 'running')
  const [run, setRun] = useState<ExamRun | null>(restoredDraft?.run ?? null)
  const [answers, setAnswers] = useState<Record<string, string[] | string>>(restoredDraft?.answers ?? {})
  const [startedAt, setStartedAt] = useState(restoredDraft?.started_at ?? '')
  const [durable, setDurable] = useState(true)
  const [draftNotice, setDraftNotice] = useState<string | null>(
    restored.status === 'ok'
      ? `已恢复你上次未提交的作答（${formatWhen(restored.draft.saved_at)} 保存）`
      : restored.status === 'expired'
        ? '上一份未提交的作答已超过 24 小时，已清除'
        : restored.status === 'invalid'
          ? '上一份未提交的作答无法恢复，已清除'
          : null,
  )
  const [result, setResult] = useState<ExamResult | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)
  /** 「再出一套笔试」先确认：出卷中/失败时不影响当前已出分的成绩可见。 */
  const [restartOpen, setRestartOpen] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pendingLeave, setPendingLeave] = useState<string | null>(null)
  const [createElapsed, setCreateElapsed] = useState(0)
  const [runElapsed, setRunElapsed] = useState(restored.status === 'ok' ? restored.elapsedS : 0)
  const [filterDirections, setFilterDirections] = useState<string[]>([])
  const [filterSubDirections, setFilterSubDirections] = useState<string[]>([])
  const [filterDifficulties, setFilterDifficulties] = useState<string[]>([])
  const [filterCount, setFilterCount] = useState<number | null>(null)

  const attemptRef = useRef(0)
  const mountedRef = useRef(true)

  // StrictMode 会挂载→卸载→再挂载：effect 体里重新置 true，否则开发态下响应全被守卫吞掉，
  // 页面永远停在「正在依据画像组卷」（出卷/判分请求其实已 200 返回）。
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // 无效草稿只在挂载后清理一次；读取保持纯函数，避免 StrictMode 第二次读到空。
  useEffect(() => {
    if (restored.status === 'expired' || restored.status === 'invalid') clearExamDraft(userId)
  }, [restored.status, userId])

  // 从「已有卷但 0 作答」恢复时也补一个本机起点；正常新卷由 startExam 写入。
  useEffect(() => {
    if (stage !== 'running' || startedAt !== '') return
    setStartedAt(new Date().toISOString())
  }, [stage, startedAt])

  const profile = profileAsync.data

  // 多选值里去掉「不限」哨兵后就是真正要下发的筛选；空数组 = 该维不过滤。
  const pickedDirections = filterDirections.filter((item) => item !== '')
  const pickedSubDirections = filterSubDirections.filter((item) => item !== '')
  const pickedDifficulties = filterDifficulties.filter((item) => item !== '')
  /** 子方向选项：未选一级方向时给全部子方向的并集（后端会按子方向自动补归属方向）。 */
  const subDirectionOptions: ChipOption<string>[] = [
    { value: '', label: '不限' },
    ...(pickedDirections.length === 0 ? DIRECTIONS : pickedDirections)
      .flatMap((direction) => SUBDIRECTIONS[direction] ?? [])
      .filter((item, index, all) => all.indexOf(item) === index)
      .map((item) => ({ value: item, label: item })),
  ]

  /** 换方向必须清掉子方向：新方向未必有当前子方向。 */
  const selectDirections = (next: string[]) => {
    setFilterDirections(next)
    setFilterSubDirections([])
  }

  // 门禁：画像请求三态直接决定空态 / 错误态（与面试页同一套约定）。
  // 画像已取到就保持 idle：按 status 判定会在重载瞬间退回 gate，把开考卡整块换成 loader。
  const gateView: 'gate' | 'empty' | 'error' | 'idle' =
    profile !== null
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
  /** D-7 / D-9：与 notice 同源的规则说明（含兜底回流数；两者皆 0 时不挂载）。 */
  const noticeHint = run
    ? proficiencyRuleHint(run.filtered_count, run.reintroduced_count)
    : null
  /** D-8：复核时复显本卷的过滤事实；L2 兜底回流也拼在同一行（r43 合并成一处）。 */
  const resultNotice = run
    ? [
        filteredNotice(run.filtered_count),
        backfillNotice(run.reintroduced_count),
        subDirectionNotice(run.sub_direction, run.sub_direction_backfill, run.questions.length),
      ]
        .filter((text): text is string => text !== null)
        .join(' · ')
    : ''
  /** r46：子方向聚焦的透明度事实（未聚焦 / 全部命中时不挂载），作答中单独一行。 */
  const subNotice = run
    ? subDirectionNotice(run.sub_direction, run.sub_direction_backfill, run.questions.length)
    : null
  const hasAnyAnswer = answeredCount > 0

  // 本地存储不可用时才保留旧的离开保护；正常情况由草稿恢复兜底，不拦 SPA 返回。
  useEffect(() => {
    if (durable || stage !== 'running' || !hasAnyAnswer) {
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
  }, [stage, hasAnyAnswer, pathname, durable])

  const confirmLeave = () => {
    const href = pendingLeave
    setPendingLeave(null)
    if (href !== null) navigate(href)
  }

  const startExam = async () => {
    if (!profile) return
    const hadResult = result !== null
    const attempt = attemptRef.current + 1
    attemptRef.current = attempt
    setStage('creating')
    setCreateError(null)
    setSubmitError(null)
    setConfirmOpen(false)
    setCreateElapsed(0)
    try {
      const created = await api.createExam({
        profile_id: profile.id,
        direction: pickedDirections.length === 0 ? null : pickedDirections,
        sub_direction: pickedSubDirections.length === 0 ? null : pickedSubDirections,
        difficulty: pickedDifficulties.length === 0 ? null : pickedDifficulties,
        question_count: filterCount,
      })
      if (attemptRef.current !== attempt || !mountedRef.current) return
      const objective = created.questions.filter((item) => item.kind !== 'text').length
      if (created.questions.length < MIN_QUESTIONS || objective < MIN_OBJECTIVE) {
        setStage(hadResult ? 'submitted' : 'idle')
        setCreateError(
          `题型异常：本次仅 ${created.questions.length} 题（客观 ${objective} 道，需 ${MIN_QUESTIONS} 题 / 客观 ${MIN_OBJECTIVE} 道），请重新生成试卷`,
        )
        return
      }
      setRun(created)
      setAnswers({})
      const nextStartedAt = new Date().toISOString()
      setStartedAt(nextStartedAt)
      setDurable(writeExamDraft(userId, { run: created, answers: {}, startedAt: nextStartedAt }))
      setDraftNotice(null)
      setResult(null)
      setRunElapsed(0)
      setStage('running')
    } catch (error) {
      if (attemptRef.current !== attempt || !mountedRef.current) return
      // 已有成绩时失败不把用户踢出结果页：原成绩与复核保持可见。
      setStage(hadResult ? 'submitted' : 'idle')
      setCreateError(error instanceof ApiError ? error.message : '组卷失败，请稍后重试')
    }
  }

  const cancelCreate = () => {
    attemptRef.current += 1
    setStage(result !== null ? 'submitted' : 'idle')
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
      clearExamDraft(userId)
      setFlow({ hasExam: true })
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
    setAnswers((prev) => {
      const next = { ...prev, [questionId]: value }
      if (run !== null && startedAt !== '') {
        if (!writeExamDraft(userId, { run, answers: next, startedAt })) setDurable(false)
      }
      return next
    })
  }

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">科考</h1>
        <p className="sc-page-sub">
          客观题本地判分，提交后 10 秒内出总分、用时与逐题对错；失败不会清空你的选择
        </p>
      </header>

      {draftNotice !== null ? (
        <div className="sc-meta-line" role="status">
          <span>{draftNotice}</span>
          <Button variant="ghost" size="sm" onClick={() => setDraftNotice(null)} aria-label="关闭草稿提示">
            关闭
          </Button>
        </div>
      ) : null}
      {!durable && (view === 'running' || view === 'submitting') ? (
        <p className="sc-meta-line" role="status">
          当前浏览器无法保存本地草稿，请保持本页打开；离开前会再次提醒你。
        </p>
      ) : null}

      {view === 'gate' ? (
        <PhaseLoader title="正在读取你的最新画像" phases={['读取画像']} active={0} />
      ) : null}

      {view === 'empty' ? (
        <ResumeGate
          reason="科考按画像方向组卷（≥10 题，其中客观题 ≥8 道自动判分）。先上传简历并确认画像，再来科考。"
          unlockLabel="回来开始笔试"
        />
      ) : null}

      {view === 'error' && profileAsync.error ? (
        <InlineError message={profileAsync.error.message} onRetry={profileAsync.reload} />
      ) : null}

      {view === 'idle' ? (
        <div className="sc-fade-in">
          <Card className="sc-exam-setup">
            <div className="sc-exam-setup-head">
              <div>
                <span className="sc-form-kicker">EXAM / SETUP</span>
                <h2 className="sc-form-section-title">按你的目标，组一场笔试</h2>
              </div>
              <span className="sc-exam-setup-mark" aria-hidden="true">↗</span>
            </div>
            <p className="sc-exam-profile">
              <span>当前画像</span>
              <strong>{profile?.target_role ?? '未填写目标岗位'}</strong>
              <span className="sc-exam-profile-meta">
                {profile?.skills.length ?? 0} 项技能 · {profile?.projects.length ?? 0} 个项目
              </span>
            </p>
            <div className="sc-qcard-head" aria-label="本卷规则">
              <Chip label="总题 ≥10" tone="direction" />
              <Chip label="客观 ≥8" tone="direction" />
              <span className="sc-exam-rule-note">提交后本地判分，不消耗 AI 配额</span>
            </div>

            <div className="sc-exam-filter-heading">
              <h3>组卷偏好</h3>
              <span>不选择时按画像智能组卷</span>
            </div>
            <div className="sc-exam-filtergroups">
              <div className="sc-lab-filter-row">
                <span className="sc-lab-filter-label">方向</span>
                <div className="sc-lab-filter-body">
                  <MultiChipRow
                    groupLabel="组卷方向筛选"
                    options={DIRECTION_OPTIONS}
                    values={filterDirections}
                    allValue=""
                    onChange={selectDirections}
                  />
                </div>
              </div>
              <div className="sc-lab-filter-row">
                <span className="sc-lab-filter-label">子方向</span>
                <div className="sc-lab-filter-body">
                  <MultiChipRow
                    groupLabel="组卷二级方向筛选"
                    options={subDirectionOptions}
                    values={filterSubDirections}
                    allValue=""
                    onChange={setFilterSubDirections}
                  />
                </div>
              </div>
              <div className="sc-lab-filter-row">
                <span className="sc-lab-filter-label">难度</span>
                <div className="sc-lab-filter-body">
                  <MultiChipRow
                    groupLabel="组卷难度筛选"
                    options={DIFFICULTY_OPTIONS}
                    values={filterDifficulties}
                    allValue=""
                    onChange={setFilterDifficulties}
                  />
                </div>
              </div>
              <div className="sc-lab-filter-row">
                <span className="sc-lab-filter-label">题量</span>
                <div className="sc-lab-filter-body">
                  <label className="sc-filter sc-exam-filtercount">
                    <Select
                      ariaLabel="题量"
                      value={filterCount === null ? '' : String(filterCount)}
                      options={QUESTION_COUNT_OPTIONS.map((opt) => ({
                        value: opt.value === null ? '' : String(opt.value),
                        label: opt.label,
                      }))}
                      onChange={(next) => setFilterCount(next === '' ? null : Number(next))}
                    />
                  </label>
                </div>
              </div>
            </div>
            <p className="sc-exam-filter-note">
              方向 / 子方向 / 难度都可多选，勾满全部具体项会自动回到「不限」；方向变化后需重新选择子方向。单选、多选与简答混排，计时从出卷后开始。
            </p>

            {createError ? (
              <InlineError message={createError} onRetry={() => void startExam()} retryLabel="重新出卷" />
            ) : null}
            <div className="sc-btn-row sc-exam-setup-actions">
              <Button onClick={() => void startExam()}>开始笔试 ↗</Button>
              <Link className="sc-btn sc-btn--ghost" to="/profile">
                先看看画像
              </Link>
            </div>
          </Card>
        </div>
      ) : null}

      {view === 'creating' ? (
        <div className="sc-fade-in">
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
        </div>
      ) : null}

      {(view === 'running' || view === 'submitting') && run ? (
        <div className="sc-fade-in">
        <>
          {/* AC-12：过滤事实 + 回流规则 + L2 兜底计数合并成一处；全为 0 时不挂载节点（零占位）。 */}
          {noticeHint ? (
            <span className="sc-meta-line">
              <Chip label="熟练过滤" />
              {' '}
              {notice ? <span>{notice}</span> : null}
              {notice ? <span>{`· ${noticeHint}`}</span> : <span>{noticeHint}</span>}
            </span>
          ) : null}

          {/* r46：选了子方向但题量不足、用同方向题补位时如实说明（未聚焦 / 全部命中不挂载）。 */}
          {subNotice ? (
            <span className="sc-meta-line">
              <Chip label="方向聚焦" />
              {' '}
              <span>{subNotice}</span>
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

          {/* 提交错误贴着提交按钮（卷面很长，放在题目列表之前用户看不到）。 */}
          {submitError ? (
            <InlineError
              message={submitError}
              onRetry={() => void submitExam()}
              retryLabel="重试提交"
            />
          ) : null}

          <div className="sc-btn-row is-end">
            <span className="sc-meta-line">
              已答 {answeredCount} / {total}
            </span>
            <Button onClick={requestSubmit} loading={submitting} disabled={submitting}>
              提交试卷
            </Button>
          </div>
        </>
        </div>
      ) : null}

      {view === 'submitted' && run && result ? (
        <div className="sc-fade-in">
        <>
          <ExamResultPanel result={result} questions={run.questions} />

          {/* D-8：复核时回看本卷的过滤事实；L2 兜底回流拼在同一行（r43），不单独挂标签。 */}
          {resultNotice ? (
            <span className="sc-meta-line">
              <Chip label="熟练过滤" />
              {' '}
              <span>{resultNotice}</span>
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
              生成医案
            </Link>
            <Button variant="secondary" onClick={() => setRestartOpen(true)}>
              再出一套笔试
            </Button>
          </div>

          {/* 已有成绩时再出卷失败：错误与重试贴着结果页，不丢失本场成绩。 */}
          {createError ? (
            <InlineError message={createError} onRetry={() => void startExam()} retryLabel="重新出卷" />
          ) : null}
        </>
        </div>
      ) : null}

      <ConfirmModal
        open={restartOpen}
        title="再出一套笔试"
        message="将按当前画像重新组卷，本场成绩与逐题复核会被新一套覆盖（本轮成绩仍会保留在战绩里）。"
        confirmLabel="重新出卷"
        cancelLabel="留在本场"
        onConfirm={() => {
          setRestartOpen(false)
          void startExam()
        }}
        onCancel={() => setRestartOpen(false)}
      />

      <ConfirmModal
        open={confirmOpen}
        title="还有题目未作答"
        message={`还有 ${total - answeredCount} 题未答。未作答的题会按错误计分；提交后本卷成绩固定，不能再改。`}
        confirmLabel="仍然提交"
        cancelLabel="继续作答"
        onConfirm={() => void submitExam()}
        onCancel={() => setConfirmOpen(false)}
      />

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
