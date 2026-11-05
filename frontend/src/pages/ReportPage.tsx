import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Report } from '../api/types'
import { scoreRingState } from '../components/interview/scoreModel'
import { SettingsBar } from '../components/interview/SettingsBar'
import { AnswerReview } from '../components/report/AnswerReview'
import { CoachBlocks } from '../components/report/CoachBlocks'
import { LearningDirectionCard } from '../components/report/LearningDirectionCard'
import { ShortfallCard } from '../components/report/ShortfallCard'
import { WeekPlan } from '../components/report/WeekPlan'
import { AiHeavyNotice } from '../components/ui/AiHeavyNotice'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { ResumeGate } from '../components/ui/ResumeGate'
import { RingProgress } from '../components/ui/RingProgress'
import { Toast } from '../components/ui/Toast'
import { polishRoleHref } from '../lib/coach'
import { formatScore } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { useAuth } from '../state/auth'
import { setFlow } from '../state/flow'

/** 生成报告的三段式阶段文案（DESIGN §0.6：AI 等待必须有文字步进，禁止只有转圈）。 */
const GENERATE_PHASES = ['汇总作答记录', '定位短板', '匹配课程']
/** 阶段步进秒数：<4s 第 1 段、<9s 第 2 段、之后第 3 段。 */
const PHASE_STEP_S = [4, 9]
/** 复制成功提示（AC-3 原文，全仓唯一字面量；文案只在此处出现，检查器断言 3 依赖它）。 */
const COPY_TOAST_MESSAGE = '已复制到剪贴板，可直接粘进笔记'

function formatPoints(value: number): string {
  if (!Number.isFinite(value)) return '—'
  const rounded = Math.round(value * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

function formatGeneratedAt(iso: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return iso
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
}

/** 导出文件名：优先用报告生成日期，日期异常时退回报告 id 前缀（文件名永不出现非法字符）。 */
function markdownFileName(report: Report): string {
  const day = report.generated_at.slice(0, 10)
  const safe = /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : report.id.slice(0, 8)
  return `诊断报告-${safe}.md`
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback
}

/**
 * `?run_ids=a,b` → 显式测评 id 列表；未带参数返回 `null`（保持「读最近一份报告」的旧语义）。
 * 从面试/笔试结果页进来时用它把报告锁定在本场，而不是服务端默认的「最近一批」。
 */
function runIdsOf(search: string): string[] | null {
  const raw = new URLSearchParams(search).get('run_ids')
  if (raw === null) return null
  const ids = raw
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item !== '')
  return ids.length === 0 ? null : ids
}

/** 本场报告的本地缓存键：同一组 run_ids 刷新时直接复用，不再重跑 AI。 */
const REPORT_CACHE_PREFIX = 'report:run_ids:'

/** 读取本场报告缓存（sessionStorage 不可用时静默回落 null，不影响正常生成）。 */
function readCachedReport(key: string): Report | null {
  try {
    const raw = window.sessionStorage.getItem(`${REPORT_CACHE_PREFIX}${key}`)
    if (raw === null) return null
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return null
    const candidate = parsed as { id?: unknown; run_ids?: unknown }
    return typeof candidate.id === 'string' && Array.isArray(candidate.run_ids)
      ? (parsed as Report)
      : null
  } catch {
    return null
  }
}

/** 写入本场报告缓存；存储满/隐私模式下静默失败（仅失去「刷新不重跑」的优化）。 */
function writeCachedReport(key: string, report: Report): void {
  try {
    window.sessionStorage.setItem(`${REPORT_CACHE_PREFIX}${key}`, JSON.stringify(report))
  } catch {
    // 忽略：缓存只是优化，不影响页面
  }
}

/** 复制失败的中文原因：浏览器拒绝/不支持剪贴板时引导用户走「导出 .md」。 */
function clipboardErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message || '复制失败，请改用「导出 .md」手动保存'
  const name = typeof error === 'object' && error !== null ? (error as { name?: unknown }).name : null
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return '浏览器拒绝访问剪贴板，请改用「导出 .md」手动保存'
  }
  return '复制失败，请改用「导出 .md」手动保存'
}

/**
 * 诊断报告页（AC-5 / AC-6 / AC-9）。
 *
 * 三条语义分开：`latest` 只读旧报告（刷新页面不重跑 AI），`generate` 是显式动作，
 * 导出走 `GET /api/reports/{id}/markdown` 的文本落到 Blob 回下载 —— 页面不二次拼串，
 * 因此导出的 .md 与页面内容天然同源（AC-9）。
 * 短板顺序一律沿用后端返回顺序（禁止前端二次排序）。
 */
export default function ReportPage() {
  const reportAsync = useAsync((signal) => api.latestReport(signal), [])
  const profileAsync = useAsync((signal) => api.latestProfile(signal), [])
  /**
   * 空态前置条件（权威判定）：history 只返回**已完成**的面试/笔试。
   * 依据它把「生成诊断报告」换成「去完成一次测评」，避免按钮点了才收到 400
   * （不用本地 flow 标记：换设备/清缓存时不失真）。
   * 取 10 条且要求「有分数」：提前结束但一题未答的会话也是 completed，它不可诊断。
   */
  const historyAsync = useAsync(() => api.history(10), [])

  const [generated, setGenerated] = useState<Report | null>(null)
  const [generating, setGenerating] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [copying, setCopying] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)
  const [toast, setToast] = useState<{ message: string; seq: number } | null>(null)
  const [elapsed, setElapsed] = useState(0)

  const mountedRef = useRef(true)
  const generatingRef = useRef(false)
  const autoStartRef = useRef('')

  // `?run_ids=`：从面试/笔试结果页进入时把报告锁定在本场；缺省仍是「读最近一份报告」。
  const { search } = useLocation()
  const { me } = useAuth()
  /** 缓存按账号分区：同一浏览器换账号后，sessionStorage 里不得再展示上一个人的报告。 */
  const cacheScope = me?.id ?? 'anon'
  const requestedRunIds = useMemo(() => runIdsOf(search), [search])
  const requestedKey = requestedRunIds === null ? '' : requestedRunIds.join(',')
  const cacheKey = requestedKey === '' ? '' : `${cacheScope}:${requestedKey}`
  const requested = requestedRunIds !== null
  /** 同一组 run_ids 的本地缓存：刷新时直接展示，不重跑 AI（无缓存时才自动生成）。 */
  const cachedReport = useMemo(
    () => (cacheKey === '' ? null : readCachedReport(cacheKey)),
    [cacheKey],
  )

  // StrictMode 会挂载→卸载→再挂载：effect 体里重新置 true，避免开发态下 setState 全被守卫吞掉
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (!generating) return
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [generating])

  // 带 ?run_ids= 时以本场报告为准：优先新生成的结果，其次是同组 id 的本地缓存（刷新不重跑）。
  const report = generated ?? (requested ? cachedReport : reportAsync.data)
  const reportMissing = reportAsync.status === 'error' && reportAsync.error?.status === 404
  const profileMissing = profileAsync.status === 'error' && profileAsync.error?.status === 404
  const profilePending = profileAsync.status !== 'success' && profileAsync.status !== 'error'
  /** history 已确认「没有一条带成绩的已完成测评」：此时生成必然 400/404，不给可点按钮。 */
  const noCompletedRun =
    historyAsync.status === 'success' &&
    !(historyAsync.data ?? []).some((run) => run.score !== null)
  const firstLoad =
    (reportAsync.status === 'loading' && report === null) || (reportMissing && profilePending)
  /** 带 ?run_ids= 进来：本场报告还没出来（生成中/尚未开始）。 */
  const requestPending = requested && report === null && generateError === null
  /** 带 ?run_ids= 进来但本场生成失败（此时不能退回展示旧报告，否则会张冠李戴）。 */
  const requestFailed = requested && report === null && generateError !== null

  // 报告真正可看时才把步骤条标记为完成（刷新后依旧以服务端报告为准）。
  useEffect(() => {
    if (report !== null) setFlow({ hasReport: true })
  }, [report])
  const generatePhase = elapsed < PHASE_STEP_S[0] ? 0 : elapsed < PHASE_STEP_S[1] ? 1 : 2

  const generateReport = useCallback(async (runIds: string[] | null = null) => {
    if (generatingRef.current) return
    generatingRef.current = true
    setGenerating(true)
    setGenerateError(null)
    setExportError(null)
    setCopyError(null)
    setToast(null)
    setElapsed(0)
    try {
      // 传 run_ids：只汇总本场；不传：服务端默认合并最近一批测评记录（前端不猜哪些记录该进报告）
      const fresh = await api.generateReport(
        runIds === null || runIds.length === 0 ? {} : { run_ids: runIds },
      )
      if (!mountedRef.current) return
      setGenerated(fresh)
      // 本场报告落缓存：同一组 run_ids 再刷新/回访直接复用，避免重复消耗 AI。
      const key = runIds === null || runIds.length === 0 ? '' : `${cacheScope}:${runIds.join(',')}`
      if (key !== '') writeCachedReport(key, fresh)
    } catch (error) {
      if (!mountedRef.current) return
      setGenerateError(errorMessage(error, '生成失败，请稍后重试；已有报告不会被覆盖'))
    } finally {
      generatingRef.current = false
      if (mountedRef.current) setGenerating(false)
    }
  }, [cacheScope])

  // 带 ?run_ids= 进入时自动生成本场报告：同一组 id 只跑一次；已有缓存则直接展示，失败后由用户点「重试」。
  useEffect(() => {
    if (cacheKey === '' || autoStartRef.current === cacheKey) return
    autoStartRef.current = cacheKey
    if (readCachedReport(cacheKey) !== null) return
    void generateReport(requestedRunIds)
  }, [cacheKey, requestedRunIds, generateReport])

  /** 重新生成沿用当前入口的 id 集：带 ?run_ids= 时仍是本场，不会退回「最近一批」。 */
  const regenerate = () => {
    void generateReport(requestedRunIds)
  }

  const exportMarkdown = async () => {
    if (!report || exporting) return
    setExporting(true)
    setExportError(null)
    try {
      // 文本来自后端唯一渲染源（services/markdown.py），前端只负责落盘
      const text = await api.reportMarkdown(report.id)
      const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = markdownFileName(report)
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      window.setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (error) {
      if (!mountedRef.current) return
      // 失败只报错不清空页面：报告仍在，用户可直接重试导出
      setExportError(errorMessage(error, '导出失败，请稍后重试'))
    } finally {
      if (mountedRef.current) setExporting(false)
    }
  }

  const copyMarkdown = async () => {
    if (!report || copying) return
    setCopying(true)
    setCopyError(null)
    try {
      // 前置能力判断（非安全上下文 / 旧浏览器）：不进 try 之外抛错，直接走失败分支
      if (typeof navigator.clipboard?.writeText !== 'function') {
        throw new ApiError('CLIPBOARD_UNAVAILABLE', '当前浏览器不支持剪贴板复制，请改用「导出 .md」手动保存', 0, true)
      }
      // 文本只有一个来源：后端唯一渲染（services/markdown.py）；此处全程零变换（AC-2）
      const text = await api.reportMarkdown(report.id)
      await navigator.clipboard.writeText(text)
      if (!mountedRef.current) return
      setToast((prev) => ({ message: COPY_TOAST_MESSAGE, seq: (prev?.seq ?? 0) + 1 }))
    } catch (error) {
      if (!mountedRef.current) return
      // 失败只报错不清空页面：报告仍在，用户可重试复制或用「导出 .md」手动兜底
      setCopyError(clipboardErrorMessage(error))
    } finally {
      if (mountedRef.current) setCopying(false)
    }
  }

  const interviewAvg = report ? report.interview_avg : null
  const examTotal = report ? report.exam_total : null

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">诊断报告</h1>
        <p className="sc-page-sub">
          短板按严重度从高到低排序，每条都带题目证据、建议动作与推荐课程
        </p>
      </header>
      <AiHeavyNotice />

      {/*
        本场设定条（AC-12 / DESIGN §2.6）：取参与本报告的最新面试设定，置于页头之下、正文之上。
        `interview_settings` 为 null（报告只含笔试 / 旧记录）→ 整行不渲染，不出现空条或「暂无」占位。
      */}
      {report?.interview_settings && !requestPending && !requestFailed ? (
        <SettingsBar settings={report.interview_settings} />
      ) : null}

      <div className="sc-profile-dim">
        {generating ? (
          <PhaseLoader
            title={requested ? '正在生成本场诊断报告' : '正在生成诊断报告'}
            phases={GENERATE_PHASES}
            active={generatePhase}
            elapsedSec={elapsed}
          />
        ) : null}

        {/* 首帧先于 effect：带 ?run_ids= 时也显示「生成本场报告」，绝不闪出旧的最近报告。 */}
        {!generating && requestPending ? (
          <PhaseLoader title="正在生成本场诊断报告" phases={GENERATE_PHASES} active={0} />
        ) : null}

        {!generating && !requested && firstLoad ? (
          <PhaseLoader title="正在读取最近一份诊断报告" phases={['读取已有报告']} active={0} />
        ) : null}

        {!generating && requestFailed ? (
          <InlineError message={generateError ?? ''} onRetry={regenerate} retryLabel="重新生成" />
        ) : null}

        {!generating && !firstLoad && !requestPending && !requestFailed && report ? (
          <div className="sc-profile-dim">
            {generateError ? (
              <InlineError message={generateError} onRetry={regenerate} retryLabel="重新生成" />
            ) : null}
            {exportError ? (
              <InlineError message={exportError} onRetry={exportMarkdown} retryLabel="重新导出" />
            ) : null}
            {copyError ? (
              <InlineError message={copyError} onRetry={copyMarkdown} retryLabel="重新复制" />
            ) : null}

            <Card>
              <div className="sc-score-side">
                <div className="sc-profile-dim">
                  <p className="sc-meta-line">面试均分</p>
                  <RingProgress
                    size={56}
                    stroke={5}
                    value={interviewAvg ?? 0}
                    max={10}
                    label={interviewAvg === null ? '—' : formatScore(interviewAvg)}
                    state={interviewAvg === null ? 'default' : scoreRingState(interviewAvg)}
                    ariaLabel={
                      interviewAvg === null
                        ? '本次报告没有面试成绩'
                        : `面试均分 ${formatScore(interviewAvg)} 分，满分 10 分`
                    }
                  />
                </div>

                <div className="sc-profile-dim">
                  <p className="sc-meta-line">笔试总分</p>
                  <p className="sc-mono">
                    {examTotal === null ? '—' : `${formatPoints(examTotal)} / 100`}
                  </p>
                </div>

                <div className="sc-profile-dim">
                  <p className="sc-meta-line">短板条数</p>
                  <p className="sc-mono">{`${report.shortfalls.length} 条`}</p>
                </div>
              </div>

              <div className="sc-btn-row">
                <p className="sc-meta-line">
                  {`生成于 ${formatGeneratedAt(report.generated_at)} · ${
                    requested ? '本场报告' : '最近一批测评'
                  } · 覆盖 ${report.run_ids.length} 次测评`}
                </p>
              </div>

              <div className="sc-btn-row">
                <Button variant="secondary" onClick={copyMarkdown} loading={copying}>
                  复制 Markdown
                </Button>
                <Button variant="primary" onClick={exportMarkdown} loading={exporting}>
                  导出 .md
                </Button>
                <Button variant="secondary" onClick={regenerate} disabled={exporting}>
                  重新生成
                </Button>
              </div>

              {/* 润色入口：只在既有按钮行之后追加，复制/导出/重生成的顺序与文案零改动（AC-14 不回归） */}
              <div className="sc-btn-row sc-report-polish">
                <p className="sc-meta-line">让简历更贴近这个目标岗位</p>
                <Link
                  className="sc-btn sc-btn--secondary is-sm"
                  to={polishRoleHref(report.role_fit?.target_role ?? null)}
                >
                  润色简历
                </Link>
              </div>
            </Card>

            <div className="sc-profile-dim">
              {report.shortfalls.map((shortfall, index) => (
                <ShortfallCard
                  key={`${shortfall.name}-${index}`}
                  shortfall={shortfall}
                  order={index + 1}
                />
              ))}
            </div>

            {/* 提升路线三块（r7）：DOM 必须在短板主轴之后（超长内容不抢首屏，AC-14） */}
            <CoachBlocks report={report} />

            {/* 推荐学习方向：目标岗位方向 + 短板课程方向，排在补强块之后、逐题复盘之前 */}
            <LearningDirectionCard report={report} />

            {/* 调研改造（boss / LeetCode 借鉴）：逐题复盘 → 7 天补短板计划，同样排在主轴之后 */}
            <AnswerReview runIds={report.run_ids} />
            <WeekPlan report={report} userId={cacheScope} />
          </div>
        ) : null}

        {!generating && !firstLoad && !requested && report === null && profileMissing ? (
          <ResumeGate
            reason="诊断报告要先有一份画像：上传简历后会自动解析技能与项目，再去做模拟面试或笔试，这里才会产出带证据的短板清单。"
            unlockLabel="回来查看诊断报告"
          />
        ) : null}

        {!generating &&
        !firstLoad &&
        !requested &&
        report === null &&
        !profileMissing &&
        profileAsync.error !== null ? (
          <InlineError message={profileAsync.error.message} onRetry={profileAsync.reload} />
        ) : null}

        {!generating &&
        !firstLoad &&
        !requested &&
        report === null &&
        !profileMissing &&
        profileAsync.error === null &&
        reportMissing ? (
          <div className="sc-profile-dim">
            {generateError ? (
              <InlineError message={generateError} onRetry={regenerate} retryLabel="重试" />
            ) : null}
            {noCompletedRun ? (
              <EmptyState
                reason="还没有可汇总的测评：先完成一轮模拟面试或笔试，再回来生成带题目证据的短板清单。"
                actionLabel="去完成一次测评"
                actionTo="/interview"
              />
            ) : (
              <EmptyState
                reason="还没有诊断报告：完成一轮面试或笔试后，这里会给出 3–5 条带题目证据的短板，按严重度排序并直连基础课程。"
                actionLabel="生成诊断报告"
                onAction={regenerate}
              />
            )}
            <div className="sc-btn-row">
              <p className="sc-meta-line">还没有作答记录？先完成一次测评</p>
              <Link className="sc-btn sc-btn--secondary" to="/interview">
                模拟面试
              </Link>
              <Link className="sc-btn sc-btn--secondary" to="/exam">
                模拟笔试
              </Link>
            </div>
          </div>
        ) : null}

        {!generating &&
        !firstLoad &&
        !requested &&
        report === null &&
        !profileMissing &&
        profileAsync.error === null &&
        !reportMissing &&
        reportAsync.error !== null ? (
          <InlineError message={reportAsync.error.message} onRetry={reportAsync.reload} />
        ) : null}
      </div>

      {toast ? (
        <Toast message={toast.message} seq={toast.seq} onClose={() => setToast(null)} />
      ) : null}
    </section>
  )
}
