import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type {
  PracticeAnswerResult,
  PracticeLanguageFilter,
  PracticePaper,
  PracticeStats,
  PracticeWrongBook,
} from '../api/types'
import { ExamQuestionCard } from '../components/exam/ExamQuestionCard'
import { SegTabs } from '../components/polish/SegTabs'
import { Explanation } from '../components/practice/Explanation'
import { PracticeFilters } from '../components/practice/PracticeFilters'
import { PracticeProgress } from '../components/practice/PracticeProgress'
import { PracticeSummary } from '../components/practice/PracticeSummary'
import { WrongBookList } from '../components/practice/WrongBookList'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { ConfirmModal } from '../components/ui/ConfirmModal'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import {
  ANSWER_ERROR_MESSAGE,
  DIFFICULTY_LABEL,
  EMPTY_BANK_REASON,
  ESSENTIALITY_LABEL,
  LANGUAGE_LABEL,
  NEED_ANSWER_MESSAGE,
  NO_HIT_MESSAGE,
  PAPER_ERROR_FALLBACK,
  STATS_ERROR_MESSAGE,
  answerText,
  filtersLabel,
  parsePracticeSearch,
  wrongTabLabel,
  type PracticeFiltersState,
} from '../lib/practice'

type View = 'setup' | 'running' | 'done'
type Tab = 'practice' | 'wrong'

const STATS_PHASES = ['读取题库统计', '统计已练与错题']
const PAPER_PHASES = ['按筛选挑题', '准备题单']

/** 非 ApiError 的异常也归一成一句中文（错误 envelope 的 message 由 client.ts 保证是中文）。 */
function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message.trim() !== '') return error.message
  return fallback
}

/**
 * 在线练习（r11 · `/practice`）：筛选 → 逐题作答 → 即时对错与解析 → 错题本。
 *
 * 边界（TECHNICAL §6.2）：
 * 1. **唯一出网点**：本页经 `api`（`lib/client.ts`）调四端点，子组件只收 props、不发请求；
 * 2. 状态只活在页面 `useState`（无新全局 store）：刷新即回 `setup`，本轮进度允许重置（AC-18），
 *    但「全库已练 m / M」恒来自服务端统计；
 * 3. 判分与笔试同源：本页**不做任何判分**，只展示服务端返回的 `correct/correct_answer/explanation`；
 * 4. 提交前页面**零答案信息**（题单响应本身不含 answer/explanation）。
 */
export default function PracticePage() {
  // 报告页「7 天计划」的专项练习链接带筛选参数：首渲染按 query 落到对应筛选，其余入口仍走默认值。
  const { search } = useLocation()
  const [tab, setTab] = useState<Tab>('practice')
  const [view, setView] = useState<View>('setup')
  const [filters, setFilters] = useState<PracticeFiltersState>(() => parsePracticeSearch(search))

  const [paper, setPaper] = useState<PracticePaper | null>(null)
  const [index, setIndex] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [feedback, setFeedback] = useState<PracticeAnswerResult | null>(null)
  const [answers, setAnswers] = useState<Record<string, boolean>>({})
  const [needAnswer, setNeedAnswer] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [starting, setStarting] = useState(false)
  const [paperError, setPaperError] = useState<string | null>(null)
  const [answerError, setAnswerError] = useState<string | null>(null)
  const [retrain, setRetrain] = useState(false)
  const [exitOpen, setExitOpen] = useState(false)

  const [stats, setStats] = useState<PracticeStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsError, setStatsError] = useState<string | null>(null)
  const [statsPulse, setStatsPulse] = useState(0)

  const [wrongBook, setWrongBook] = useState<PracticeWrongBook | null>(null)
  const [wrongLanguage, setWrongLanguage] = useState<PracticeLanguageFilter>('all')
  const [wrongLoading, setWrongLoading] = useState(false)
  const [wrongError, setWrongError] = useState<string | null>(null)
  const [wrongPulse, setWrongPulse] = useState(0)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const statsSeq = useRef(0)
  const cardRef = useRef<HTMLDivElement>(null)
  const feedbackRef = useRef<HTMLDivElement>(null)
  const needRef = useRef<HTMLParagraphElement>(null)
  /** 最近一次出题请求的来源（筛选条件 + 是否错题重练）：失败重试按来源原样重放。 */
  const paperRequestRef = useRef<{ filters: PracticeFiltersState; retrain: boolean } | null>(null)

  const reloadStats = useCallback(() => setStatsPulse((value) => value + 1), [])

  /**
   * 统计：筛选一变就重取（命中行常驻，不因请求闪烁消失）。
   * 请求序号丢弃过期响应 —— 连续点 chip 时慢响应不得覆盖新筛选（DESIGN §3-1）。
   */
  useEffect(() => {
    const seq = statsSeq.current + 1
    statsSeq.current = seq
    const controller = new AbortController()
    setStatsLoading(true)
    setStatsError(null)
    api
      .practiceStats(
        {
          language: filters.language,
          direction: filters.direction,
          difficulty: filters.difficulty,
          essentiality: filters.essentiality,
          scope: filters.scope,
        },
        controller.signal,
      )
      .then((next) => {
        if (statsSeq.current !== seq || controller.signal.aborted) return
        setStats(next)
        setStatsLoading(false)
      })
      .catch((error: unknown) => {
        if (statsSeq.current !== seq || controller.signal.aborted) return
        setStatsError(messageOf(error, STATS_ERROR_MESSAGE))
        setStatsLoading(false)
      })
    return () => controller.abort()
  }, [
    filters.language,
    filters.direction,
    filters.difficulty,
    filters.essentiality,
    filters.scope,
    statsPulse,
  ])

  /** 错题本：切到该 tab 才请求，语言过滤变化重取（服务端定序，前端不排序）。 */
  useEffect(() => {
    if (tab !== 'wrong') return
    const controller = new AbortController()
    setWrongLoading(true)
    setWrongError(null)
    api
      .practiceWrongBook(wrongLanguage, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return
        setWrongBook(next)
        setWrongLoading(false)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setWrongError(messageOf(error, PAPER_ERROR_FALLBACK))
        setWrongLoading(false)
      })
    return () => controller.abort()
  }, [tab, wrongLanguage, wrongPulse])

  // 换题 / 进入作答态：焦点落到题卡（读屏先读「第 i / N 题」，DESIGN §3-5）。
  useEffect(() => {
    if (view === 'running') cardRef.current?.focus()
  }, [view, index])

  // 判分成功：焦点移到反馈块（先读「✓ 正确，正确答案 A」，DESIGN §2.3）。
  useEffect(() => {
    if (feedback) feedbackRef.current?.focus()
  }, [feedback])

  const total = paper ? paper.questions.length : 0
  const current = paper && index < paper.questions.length ? paper.questions[index] : null
  const correctCount = Object.values(answers).filter(Boolean).length
  const answeredCount = Object.keys(answers).length
  const wrongTotal = stats ? stats.wrong_total : 0
  const bankEmpty = stats !== null && stats.total === 0
  const firstLoading = stats === null && statsLoading

  const startPaper = async (nextFilters: PracticeFiltersState, isRetrain: boolean) => {
    paperRequestRef.current = { filters: { ...nextFilters }, retrain: isRetrain }
    setStarting(true)
    setPaperError(null)
    try {
      const next = await api.practicePaper({
        language: nextFilters.language,
        direction: nextFilters.direction,
        difficulty: nextFilters.difficulty,
        essentiality: nextFilters.essentiality,
        scope: nextFilters.scope,
        limit: nextFilters.limit,
      })
      if (next.questions.length === 0) {
        setPaper(null)
        setView('setup')
        setRetrain(false)
        setPaperError(next.notice !== '' ? next.notice : NO_HIT_MESSAGE)
        return
      }
      setFilters(nextFilters)
      setPaper(next)
      setIndex(0)
      setSelected([])
      setFeedback(null)
      setAnswers({})
      setAnswerError(null)
      setNeedAnswer(false)
      setExpandedId(null)
      setRetrain(isRetrain)
      setTab('practice')
      setView('running')
    } catch (error: unknown) {
      setPaperError(messageOf(error, PAPER_ERROR_FALLBACK))
    } finally {
      setStarting(false)
    }
  }

  const submitAnswer = async () => {
    if (!paper || !current) return
    if (selected.length === 0) {
      // 不禁用按钮（避免死按钮），给红字并把焦点移过去（DESIGN §0.3）。
      setNeedAnswer(true)
      window.requestAnimationFrame(() => needRef.current?.focus())
      return
    }
    setSubmitting(true)
    setAnswerError(null)
    setNeedAnswer(false)
    try {
      const result = await api.practiceAnswer({
        session_id: paper.session_id,
        question_id: current.id,
        answer: selected,
      })
      setFeedback(result)
      setAnswers((previous) => ({ ...previous, [current.id]: result.correct }))
    } catch {
      // 保留已选答案：失败后重试复用同一份选择，不重开题单（DESIGN §3-6）。
      setAnswerError(ANSWER_ERROR_MESSAGE)
    } finally {
      setSubmitting(false)
    }
  }

  const advance = () => {
    if (!paper) return
    if (index + 1 >= paper.questions.length) {
      setView('done')
      setStatsPulse((value) => value + 1)
      setWrongPulse((value) => value + 1)
      return
    }
    setIndex((value) => value + 1)
    setSelected([])
    setFeedback(null)
    setAnswerError(null)
    setNeedAnswer(false)
  }

  const resetToSetup = () => {
    setView('setup')
    setPaper(null)
    setSelected([])
    setFeedback(null)
    setAnswers({})
    setAnswerError(null)
    setNeedAnswer(false)
    setRetrain(false)
  }

  const changeTab = (key: string) => {
    if (key !== 'practice' && key !== 'wrong') return
    setTab(key)
    if (key === 'wrong') setWrongPulse((value) => value + 1)
  }

  const retrainWrong = () => {
    void startPaper(
      {
        language: wrongLanguage,
        direction: 'all',
        difficulty: 'all',
        essentiality: 'all',
        scope: 'wrong',
        limit: 0,
      },
      true,
    )
  }

  const feedbackFooter =
    feedback && current ? (
      <>
        <div
          className="sc-qa-feedback"
          role="status"
          aria-live="polite"
          tabIndex={-1}
          ref={feedbackRef}
        >
          <div className="sc-qa-feedback-head">
            <span className={feedback.correct ? 'sc-qa-mark is-correct' : 'sc-qa-mark is-wrong'}>
              {feedback.correct ? '✓ 正确' : '✗ 错误'}
            </span>
            <span className="sc-qa-answer-label">正确答案：</span>
            <span className="sc-mono sc-qa-answer">{answerText(feedback.correct_answer)}</span>
          </div>
          <Explanation text={feedback.explanation} />
        </div>
        {answerError ? (
          <InlineError message={answerError} onRetry={() => void submitAnswer()} />
        ) : null}
      </>
    ) : null

  const needFooter =
    !feedback && needAnswer ? (
      <p className="sc-qa-need" tabIndex={-1} ref={needRef}>
        {NEED_ANSWER_MESSAGE}
      </p>
    ) : null

  const cardFooter =
    feedbackFooter ?? (
      <>
        {needFooter}
        {answerError ? (
          <InlineError message={answerError} onRetry={() => void submitAnswer()} />
        ) : null}
      </>
    )

  const renderRunning = () => {
    if (!paper || !current) return null
    return (
      <>
        <div className="sc-qa-running-head">
          <PracticeProgress
            index={index + 1}
            total={total}
            correct={correctCount}
            answered={answeredCount}
          />
          <div className="sc-qa-running-tools">
            {retrain ? <Chip label="错题重练" /> : null}
            <Button variant="ghost" size="sm" onClick={() => setExitOpen(true)}>
              退出本轮
            </Button>
          </div>
        </div>
        {paper.notice !== '' ? <p className="sc-meta-line">{paper.notice}</p> : null}
        <div
          className="sc-qa-cardwrap"
          tabIndex={-1}
          role="group"
          aria-label={`第 ${index + 1} / ${total} 题`}
          ref={cardRef}
        >
          <p className="sc-qa-question-tags">
            <Chip label={LANGUAGE_LABEL[current.language]} />
            {current.direction !== '' ? <Chip label={current.direction} tone="direction" /> : null}
            <Chip label={DIFFICULTY_LABEL[current.difficulty]} />
            <Chip label={ESSENTIALITY_LABEL[current.essentiality]} />
          </p>
          <ExamQuestionCard
            index={index}
            question={current}
            value={selected}
            onChange={(value) => {
              if (feedback) return
              setSelected(Array.isArray(value) ? value : [value])
              setNeedAnswer(false)
            }}
            review={
              feedback
                ? {
                    question_id: feedback.question_id,
                    correct: feedback.correct,
                    your_answer: selected,
                    correct_answer: feedback.correct_answer,
                  }
                : null
            }
            locked={submitting}
            footer={cardFooter}
          />
        </div>
        <div className="sc-qa-actions">
          {feedback ? (
            <Button onClick={advance}>{index + 1 >= total ? '查看本轮结果' : '下一题'}</Button>
          ) : (
            <Button onClick={() => void submitAnswer()} loading={submitting}>
              {submitting ? '判分中…' : '提交答案'}
            </Button>
          )}
        </div>
      </>
    )
  }

  const renderPractice = () => {
    if (firstLoading) {
      return <PhaseLoader title="正在读取题库统计" phases={STATS_PHASES} active={0} />
    }
    if (statsError !== null && stats === null) {
      return <InlineError message={statsError} onRetry={reloadStats} />
    }
    if (bankEmpty) {
      return <EmptyState reason={EMPTY_BANK_REASON} actionLabel="重试" onAction={reloadStats} />
    }
    if (view === 'running') return renderRunning()
    if (view === 'done' && paper) {
      return (
        <PracticeSummary
          total={total}
          correct={correctCount}
          wrongCount={wrongTotal}
          filtersLabel={filtersLabel(filters)}
          onWrongBook={() => changeTab('wrong')}
          onAgain={() => void startPaper(filters, retrain)}
          onReset={resetToSetup}
        />
      )
    }
    return (
      <PracticeFilters
        filters={filters}
        onChange={(patch) => setFilters((previous) => ({ ...previous, ...patch }))}
        hitCount={stats ? stats.hit : null}
        hitLoading={statsLoading}
        globalStats={stats}
        onStart={() => void startPaper(filters, false)}
        startLoading={starting}
      />
    )
  }

  const renderWrong = () => {
    if (wrongLoading && wrongBook === null) {
      return <PhaseLoader title="正在读取错题本" phases={['读取错题本', '按语言过滤']} active={0} />
    }
    if (wrongError !== null && wrongBook === null) {
      return <InlineError message={wrongError} onRetry={() => setWrongPulse((value) => value + 1)} />
    }
    return (
      <WrongBookList
        items={wrongBook ? wrongBook.items : []}
        total={wrongBook ? wrongBook.total : 0}
        language={wrongLanguage}
        expandedId={expandedId}
        onToggle={(questionId) =>
          setExpandedId((previous) => (previous === questionId ? null : questionId))
        }
        onFilterLanguage={(value) => {
          setWrongLanguage(value)
          setExpandedId(null)
        }}
        onRetrain={retrainWrong}
        onStartPractice={() => {
          // 空态出口「开始练习」= 回筛选重新挑题（不是回到上一轮的完成态）
          resetToSetup()
          changeTab('practice')
          reloadStats()
        }}
      />
    )
  }

  return (
    <div className="sc-qa-col">
      <header className="sc-page-header">
        <h1 className="sc-page-title">在线练习</h1>
        <p className="sc-page-sub">
          按语言挑题，提交即出对错与解析；判分与笔试同源，答对会累计进熟练度
        </p>
      </header>

      <div className="sc-qa-tabs">
        <SegTabs
          tabs={[
            { key: 'practice', label: '练习' },
            { key: 'wrong', label: wrongTabLabel(wrongTotal) },
          ]}
          active={tab}
          onChange={changeTab}
          ariaLabel="练习与错题本切换"
        />
      </div>

      {tab === 'practice' ? renderPractice() : renderWrong()}

      {/* 出题失败 / 挑题中都放在三视图共享区：完成态与错题本发起新一轮同样能看到反馈。 */}
      {paperError ? (
        <InlineError
          message={paperError}
          onRetry={() => {
            const last = paperRequestRef.current
            if (last !== null) void startPaper(last.filters, last.retrain)
          }}
          retryLabel="重试"
        />
      ) : null}
      {starting ? (
        <PhaseLoader title="正在按筛选挑题" phases={PAPER_PHASES} active={0} />
      ) : null}

      <ConfirmModal
        open={exitOpen}
        title="退出本轮练习"
        message="退出后本轮进度不保留，已提交的对错仍会计入熟练度"
        confirmLabel="退出"
        cancelLabel="继续练习"
        onConfirm={() => {
          setExitOpen(false)
          resetToSetup()
          reloadStats()
        }}
        onCancel={() => setExitOpen(false)}
      />
    </div>
  )
}
