import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type {
  InterviewRun,
  InterviewSession,
  InterviewSettingsPatch,
  InterviewTurn,
} from '../api/types'
import { ChatStream } from '../components/interview/ChatStream'
import { Composer } from '../components/interview/Composer'
import { InterviewSetupForm } from '../components/interview/InterviewSetupForm'
import { draftToPatch, prefillOf } from '../components/interview/setupModel'
import type { SetupDraft, SetupSources } from '../components/interview/setupModel'
import { SessionSummary } from '../components/interview/SessionSummary'
import { SettingsBar } from '../components/interview/SettingsBar'
import { Button } from '../components/ui/Button'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { ResumeGate } from '../components/ui/ResumeGate'
import { useAsync } from '../lib/useAsync'
import { setFlow } from '../state/flow'

/** 页面阶段（TECHNICAL §4.1）：gate / empty / error 由画像请求派生，其余为用户推进后的确定态。 */
type Stage = 'configure' | 'creating' | 'chat' | 'ended'

/** 单场运行态（TECHNICAL §4.1）：一次轮次只更新这一个对象，避免散落的 loading/error 布尔。 */
interface RunTrack {
  submitting: boolean
  elapsedS: number
  /** 开局失败（配置卡内 InlineError，四项原样保留）。 */
  error: string | null
  /** 单轮失败 / 超时（输入区上方 InlineError，答案留在 textarea）。 */
  turnError: string | null
}

const EMPTY_TRACK: RunTrack = { submitting: false, elapsedS: 0, error: null, turnError: null }

/** 开局三段式文案（DESIGN §0.4：AI 调用禁止只有转圈）。 */
const CREATE_PHASES = ['读取本场设定', '生成面试计划', '准备第一问']
/** 会话恢复文案（?run_id=）。 */
const RESTORE_PHASES = ['正在恢复本场会话']

interface RestoreState {
  status: 'idle' | 'loading' | 'error'
  error: string | null
}

/** 错误 envelope 统一由 client.ts 归一；非 ApiError 也回落中文文案（AC-13）。 */
function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message) return error.message
  return fallback
}

/** 开局响应 → 会话镜像（后端为唯一真相：开局只投放第 1 条发言，答案/分数为空）。 */
function sessionOf(run: InterviewRun): InterviewSession {
  return {
    run_id: run.run_id,
    status: 'running',
    settings: run.settings,
    questions: [{ ...run.question, answer: null, score: null, comment: null }],
    answered_count: 0,
    total: run.total,
    current_id: run.question.id,
    interview_avg: null,
  }
}

/**
 * 模拟面试（AC-4 / AC-5 / AC-9 / AC-18）：七态编排 —— 配置 → 开局 → 多轮对话 → 结束；
 * `?run_id=` 恢复整场会话（已完成为只读）。页面只做编排与单一 session state（后端镜像），
 * 气泡/评分/输入区/汇总的渲染与纯函数全部在 components/interview/ 下。
 */
export default function InterviewPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const runIdParam = searchParams.get('run_id')

  const profileAsync = useAsync((signal) => api.latestProfile(signal), [])
  const createAbortRef = useRef<AbortController | null>(null)
  const prefilledIdRef = useRef<string | null>(null)
  const activeRunIdRef = useRef<string | null>(null)

  /** 会话唯一真相：后端 GET/开局/轮次返回的镜像，页面不做 payload 解析。 */
  const [session, setSession] = useState<InterviewSession | null>(null)
  const [stage, setStage] = useState<Stage>('configure')
  const [draft, setDraft] = useState<SetupDraft>(() => prefillOf(null).draft)
  const [prefill, setPrefill] = useState<SetupDraft>(() => prefillOf(null).draft)
  const [sources, setSources] = useState<SetupSources>(() => prefillOf(null).sources)
  const [track, setTrack] = useState<RunTrack>(EMPTY_TRACK)
  const [answer, setAnswer] = useState('')
  const [restore, setRestore] = useState<RestoreState>({ status: 'idle', error: null })
  /** 「重新读取」计数：run_id 不变时靠它触发恢复 effect 重跑。 */
  const [restoreTick, setRestoreTick] = useState(0)

  const profile = profileAsync.data

  // 画像到手即预填（同一画像只应用一次，重载不覆盖用户手改）。
  useEffect(() => {
    if (!profile) return
    if (prefilledIdRef.current === profile.id) return
    prefilledIdRef.current = profile.id
    const prefilled = prefillOf(profile)
    setDraft(prefilled.draft)
    setPrefill(prefilled.draft)
    setSources(prefilled.sources)
  }, [profile])

  // ?run_id= 恢复：GET 会话镜像 → running 续答 / completed 只读。
  useEffect(() => {
    if (!runIdParam) return
    if (activeRunIdRef.current === runIdParam) return
    const controller = new AbortController()
    setRestore({ status: 'loading', error: null })
    api
      .getInterview(runIdParam, controller.signal)
      .then((restored) => {
        if (controller.signal.aborted) return
        activeRunIdRef.current = restored.run_id
        setSession(restored)
        setAnswer('')
        setTrack(EMPTY_TRACK)
        setRestore({ status: 'idle', error: null })
        setStage(restored.status === 'completed' ? 'ended' : 'chat')
        if (restored.status === 'completed') setFlow({ hasInterview: true })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setRestore({ status: 'error', error: messageOf(error, '无法恢复本场面试') })
      })
    return () => controller.abort()
  }, [runIdParam, restoreTick])

  // 开局计时（三段文案按秒步进）+ 单轮评分计时。
  useEffect(() => {
    if (stage !== 'creating') return
    const timer = window.setInterval(() => {
      setTrack((prev) => ({ ...prev, elapsedS: prev.elapsedS + 1 }))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [stage])

  useEffect(() => {
    if (!track.submitting) return
    const timer = window.setInterval(() => {
      setTrack((prev) => (prev.submitting ? { ...prev, elapsedS: prev.elapsedS + 1 } : prev))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [track.submitting])

  useEffect(() => {
    return () => {
      createAbortRef.current?.abort()
    }
  }, [])

  const reloadRestore = () => {
    if (!runIdParam) return
    activeRunIdRef.current = null
    setRestore({ status: 'loading', error: null })
    setRestoreTick((value) => value + 1)
  }

  /** 开局（AC-1）：patch 省略 = 跳过表单，由服务端 fill_settings 补全（不把表单清空）。 */
  const startSession = async (patch?: InterviewSettingsPatch) => {
    if (!profile) return
    createAbortRef.current?.abort()
    const controller = new AbortController()
    createAbortRef.current = controller
    setTrack(EMPTY_TRACK)
    setStage('creating')
    try {
      const run = await api.createInterview({ profile_id: profile.id, settings: patch })
      if (controller.signal.aborted) return
      activeRunIdRef.current = run.run_id
      setSession(sessionOf(run))
      setAnswer('')
      setStage('chat')
      setSearchParams({ run_id: run.run_id }, { replace: true })
    } catch (error) {
      if (controller.signal.aborted) return
      setTrack({ ...EMPTY_TRACK, error: messageOf(error, '开局失败，请重试') })
      setStage('configure')
    }
  }

  const cancelCreate = () => {
    createAbortRef.current?.abort()
    setTrack(EMPTY_TRACK)
    setStage('configure')
  }

  /** 单轮提交（TECHNICAL §4.3）：失败只报错，答案与已答气泡原样保留。 */
  const submitTurn = async () => {
    if (!session || !session.current_id || track.submitting) return
    const questionId = session.current_id
    const text = answer.trim()
    if (text.length === 0) return
    setTrack({ submitting: true, elapsedS: 0, error: null, turnError: null })
    try {
      const turn: InterviewTurn = await api.scoreAnswer(session.run_id, {
        question_id: questionId,
        answer: text,
      })
      setSession((prev) => {
        if (!prev) return prev
        const answered = prev.questions.map((item) =>
          item.id === questionId
            ? { ...item, answer: text, score: turn.score, comment: turn.comment }
            : item,
        )
        const next = turn.next_question
          ? [{ ...turn.next_question, answer: null, score: null, comment: null }]
          : []
        return {
          ...prev,
          status: turn.run_status,
          answered_count: turn.answered_count,
          interview_avg: turn.interview_avg,
          questions: [...answered, ...next],
          current_id: turn.next_question ? turn.next_question.id : null,
        }
      })
      setAnswer('')
      setTrack((prev) => ({ ...prev, submitting: false, elapsedS: 0 }))
      if (!turn.next_question) {
        setStage('ended')
        setFlow({ hasInterview: true })
      }
    } catch (error) {
      setTrack((prev) => ({
        ...prev,
        submitting: false,
        turnError: messageOf(error, '评分失败或超时，你的答案已保留，可直接重试'),
      }))
    }
  }

  /** 重开一场：清会话与 ?run_id=，按当前画像重新预填。 */
  const restart = () => {
    createAbortRef.current?.abort()
    activeRunIdRef.current = null
    setSession(null)
    setAnswer('')
    setTrack(EMPTY_TRACK)
    setStage('configure')
    setRestore({ status: 'idle', error: null })
    setSearchParams({}, { replace: true })
    const prefilled = prefillOf(profile)
    setDraft(prefilled.draft)
    setPrefill(prefilled.draft)
    setSources(prefilled.sources)
  }

  // 门禁：画像请求三态直接决定加载 / 空态 / 错误态（ready 才进配置卡）。
  const profileView: 'loading' | 'empty' | 'error' | 'ready' =
    profileAsync.status === 'success'
      ? 'ready'
      : profileAsync.status === 'error'
        ? profileAsync.error?.status === 404
          ? 'empty'
          : 'error'
        : 'loading'
  // 恢复中：带 ?run_id= 且会话未就绪（首帧也算，避免闪一帧配置卡）；失败态单独走错误分支。
  const restoring = runIdParam !== null && session === null && restore.status !== 'error'
  const creating = stage === 'creating'
  const hasSession = session !== null

  let content: ReactNode = null

  if (restoring) {
    content = (
      <PhaseLoader title="正在恢复本场会话" phases={RESTORE_PHASES} active={0} elapsedSec={track.elapsedS} />
    )
  } else if (restore.status === 'error') {
    content = (
      <div className="sc-qcard">
        <InlineError
          message={restore.error ?? '无法恢复本场面试'}
          onRetry={reloadRestore}
          retryLabel="重新读取"
        />
        <div className="sc-btn-row">
          <Button variant="ghost" onClick={restart}>
            开新一场
          </Button>
        </div>
      </div>
    )
  } else if (hasSession && (stage === 'chat' || stage === 'ended')) {
    const current = stage === 'ended' || session.status === 'completed' ? 'ended' : 'chat'
    content = (
      <div className="sc-iq-col">
        <p className="sc-iq-meta">
          已提出 {session.questions.length} 题 · 已答 {session.answered_count} 题
          {current === 'ended' ? ' · 本场已结束' : ''}
        </p>
        <SettingsBar settings={session.settings} />
        <ChatStream questions={session.questions} pending={track.submitting} />
        {current === 'ended' ? (
          <>
            <p className="sc-iq-readonly">本场面试已结束 · 输入区已关闭</p>
            <SessionSummary
              runId={session.run_id}
              questions={session.questions}
              settings={session.settings}
              onRestart={restart}
            />
          </>
        ) : (
          <Composer
            value={answer}
            onChange={setAnswer}
            onSubmit={() => void submitTurn()}
            submitting={track.submitting}
            disabled={track.submitting}
            readonly={false}
            elapsedS={track.elapsedS}
            error={track.turnError}
          />
        )}
      </div>
    )
  } else if (creating) {
    content = (
      <div className="sc-iq-col">
        <PhaseLoader
          title="正在准备本场面试"
          phases={CREATE_PHASES}
          active={track.elapsedS < 2 ? 0 : track.elapsedS < 5 ? 1 : 2}
          elapsedSec={track.elapsedS}
        />
        <div className="sc-btn-row">
          <Button variant="ghost" onClick={cancelCreate}>
            取消
          </Button>
        </div>
      </div>
    )
  } else if (profileView === 'loading') {
    content = <PhaseLoader title="正在读取你的最新画像" phases={['读取画像']} active={0} />
  } else if (profileView === 'empty') {
    content = (
      <ResumeGate
        reason="模拟面试会依据你的画像出题（技术题 ≥5 · 项目深挖 ≥3 · 进阶 ≤20%）。先上传简历并确认画像，再来测评。"
        unlockLabel="回来开始面试"
      />
    )
  } else if (profileView === 'error') {
    content = (
      <InlineError
        message={profileAsync.error?.message ?? '画像读取失败，请稍后重试'}
        onRetry={profileAsync.reload}
      />
    )
  } else {
    content = (
      <div className="sc-iq-col">
        <p className="sc-iq-meta">本场尚未开始 · 配置后开始对话</p>
        <InterviewSetupForm
          draft={draft}
          sources={sources}
          prefill={prefill}
          submitting={creating}
          error={track.error}
          profileYears={profile?.years_experience ?? null}
          onDraft={setDraft}
          onStart={() => void startSession(draftToPatch(draft))}
          onSkip={() => void startSession()}
        />
      </div>
    )
  }

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">模拟面试</h1>
        <p className="sc-page-sub">
          多轮对话式面试：每题 0–10 分与逐字点评长在你的回答里；首问之后每轮只出一道，失败不会清空你的答案
        </p>
      </header>
      {content}
    </section>
  )
}
