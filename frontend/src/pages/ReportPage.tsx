import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Report } from '../api/types'
import { scoreRingState } from '../components/interview/ScoreBadge'
import { ShortfallCard } from '../components/report/ShortfallCard'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { RingProgress } from '../components/ui/RingProgress'
import { Toast } from '../components/ui/Toast'
import { formatScore } from '../lib/format'
import { useAsync } from '../lib/useAsync'

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

  const report = generated ?? reportAsync.data
  const reportMissing = reportAsync.status === 'error' && reportAsync.error?.status === 404
  const profileMissing = profileAsync.status === 'error' && profileAsync.error?.status === 404
  const profilePending = profileAsync.status !== 'success' && profileAsync.status !== 'error'
  const firstLoad =
    (reportAsync.status === 'loading' && report === null) || (reportMissing && profilePending)
  const generatePhase = elapsed < PHASE_STEP_S[0] ? 0 : elapsed < PHASE_STEP_S[1] ? 1 : 2

  const generateReport = async () => {
    if (generating) return
    setGenerating(true)
    setGenerateError(null)
    setExportError(null)
    setCopyError(null)
    setToast(null)
    setElapsed(0)
    try {
      // 不传 run_ids：服务端默认合并最近一批测评记录（前端不猜哪些记录该进报告）
      const fresh = await api.generateReport({})
      if (!mountedRef.current) return
      setGenerated(fresh)
    } catch (error) {
      if (!mountedRef.current) return
      setGenerateError(errorMessage(error, '生成失败，请稍后重试；已有报告不会被覆盖'))
    } finally {
      if (mountedRef.current) setGenerating(false)
    }
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

      <div className="sc-profile-dim">
        {generating ? (
          <PhaseLoader
            title="正在生成诊断报告"
            phases={GENERATE_PHASES}
            active={generatePhase}
            elapsedSec={elapsed}
          />
        ) : null}

        {!generating && firstLoad ? (
          <PhaseLoader title="正在读取最近一份诊断报告" phases={['读取已有报告']} active={0} />
        ) : null}

        {!generating && !firstLoad && report ? (
          <div className="sc-profile-dim">
            {generateError ? (
              <InlineError message={generateError} onRetry={generateReport} retryLabel="重新生成" />
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
                  {`生成于 ${formatGeneratedAt(report.generated_at)} · 覆盖 ${report.run_ids.length} 次测评`}
                </p>
              </div>

              <div className="sc-btn-row">
                <Button variant="secondary" onClick={copyMarkdown} loading={copying}>
                  复制 Markdown
                </Button>
                <Button variant="primary" onClick={exportMarkdown} loading={exporting}>
                  导出 .md
                </Button>
                <Button variant="secondary" onClick={generateReport} disabled={exporting}>
                  重新生成
                </Button>
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
          </div>
        ) : null}

        {!generating && !firstLoad && report === null && profileMissing ? (
          <EmptyState
            reason="诊断报告要先有一份画像：上传简历后会自动解析技能与项目，再去做模拟面试或笔试，这里才会产出带证据的短板清单。"
            actionLabel="上传简历"
            actionTo="/"
          />
        ) : null}

        {!generating &&
        !firstLoad &&
        report === null &&
        !profileMissing &&
        profileAsync.error !== null ? (
          <InlineError message={profileAsync.error.message} onRetry={profileAsync.reload} />
        ) : null}

        {!generating &&
        !firstLoad &&
        report === null &&
        !profileMissing &&
        profileAsync.error === null &&
        reportMissing ? (
          <div className="sc-profile-dim">
            {generateError ? (
              <InlineError message={generateError} onRetry={generateReport} retryLabel="重试" />
            ) : null}
            <EmptyState
              reason="还没有诊断报告：完成一轮面试或笔试后，这里会给出 3–5 条带题目证据的短板，按严重度排序并直连基础课程。"
              actionLabel="生成诊断报告"
              onAction={generateReport}
            />
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
