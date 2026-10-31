import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { PolishSuggestion } from '../api/types'
import { ComposePreview } from '../components/polish/ComposePreview'
import { SegTabs } from '../components/polish/SegTabs'
import { SuggestionCard, type SuggestionState } from '../components/polish/SuggestionCard'
import { TargetRoleBar } from '../components/polish/TargetRoleBar'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { ConfirmModal } from '../components/ui/ConfirmModal'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { Toast } from '../components/ui/Toast'
import { useAsync } from '../lib/useAsync'

/** 建议生成三段文案（DESIGN §0.6：AI 等待必须有文字步进）。 */
const ANALYSIS_PHASES = ['读取简历正文', '生成逐条建议', '事实校验']
const ANALYSIS_STEP_S = [4, 9]
/** 成稿生成三段文案。 */
const GENERATE_PHASES = ['汇总已采纳条目', '重写段落', '拼装成稿']
const GENERATE_STEP_S = [3, 8]

const TAB_ITEMS = [
  { key: 'original', label: '原版' },
  { key: 'polished', label: '润色版' },
]

const EXPORT_TOAST_MESSAGE = '已导出润色版 .md'

interface PolishSession {
  polishId: string
  resumeId: string
  targetRole: string | null
  suggestions: PolishSuggestion[]
  droppedCount: number
  insufficientReason: string | null
}

interface GeneratedFull {
  markdown: string
  droppedCount: number
  regenerated: boolean
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback
}

function exportFileName(): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  const day = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
  return `简历润色-${day}.md`
}

/** 按 `start` 升序（服务端按正文顺序返回，这里只防乱序，不做二次语义排序）。 */
function inResumeOrder(suggestions: PolishSuggestion[]): PolishSuggestion[] {
  return [...suggestions].sort((left, right) => left.start - right.start)
}

function phaseOf(elapsed: number, steps: number[]): number {
  if (elapsed < steps[0]) return 0
  if (elapsed < steps[1]) return 1
  return 2
}

/** 本地预览：已采纳替换、忽略/待处理保留原句。文本一律取自服务端建议的逐字映射，零裁剪零拼接。 */
function buildPreview(suggestions: PolishSuggestion[], states: Record<string, SuggestionState>): string {
  const ordered = inResumeOrder(suggestions)
  return ordered
    .map((item) => (states[item.id] === 'adopted' ? item.suggested_text : item.original_text))
    .join('\n\n')
}

function buildOriginal(suggestions: PolishSuggestion[]): string {
  return inResumeOrder(suggestions)
    .map((item) => item.original_text)
    .join('\n\n')
}

/**
 * 简历润色页（AC-8 ~ AC-12）。
 *
 * 三条边界：
 * 1. 进页**不自动烧 AI**（显式「开始分析」才请求，建议可重跑、成本可控）；
 * 2. 采纳/忽略只改本页预览，绝不写 `documents.text`（AC-10），也不做跨会话持久化；
 * 3. 导出只取 `/polish/full` 响应 `markdown`，前端零 trim/replace/拼接（AC-11 单源）。
 */
export default function PolishPage() {
  const profileAsync = useAsync((signal) => api.latestProfile(signal), [])
  const profile = profileAsync.data
  const navigate = useNavigate()
  const { pathname } = useLocation()

  const [session, setSession] = useState<PolishSession | null>(null)
  const [states, setStates] = useState<Record<string, SuggestionState>>({})
  const [filter, setFilter] = useState<'all' | 'pending'>('all')
  const [roleInput, setRoleInput] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeElapsed, setAnalyzeElapsed] = useState(0)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)
  const [changedNotice, setChangedNotice] = useState(false)

  const [full, setFull] = useState<GeneratedFull | null>(null)
  const [generating, setGenerating] = useState(false)
  const [genElapsed, setGenElapsed] = useState(0)
  const [genError, setGenError] = useState<string | null>(null)
  const [adoptionSnapshot, setAdoptionSnapshot] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [tab, setTab] = useState<'original' | 'polished'>('polished')
  const [toast, setToast] = useState<{ message: string; seq: number } | null>(null)
  const [pendingLeave, setPendingLeave] = useState<string | null>(null)
  const [composeOpen, setComposeOpen] = useState(false)
  const [wide, setWide] = useState(() =>
    typeof window === 'undefined' ? true : window.matchMedia('(min-width: 1320px)').matches,
  )

  const mountedRef = useRef(true)
  const profileInitializedRef = useRef(false)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // 目标岗位输入默认回显画像岗位（只回填一次，不覆盖用户输入）
  useEffect(() => {
    if (profileInitializedRef.current || profile === null) return
    profileInitializedRef.current = true
    setRoleInput(profile.target_role ?? '')
  }, [profile])

  // 宽窄屏：<1320 单栏，成稿区折叠为按钮（DESIGN §0.5-7）
  useEffect(() => {
    const query = window.matchMedia('(min-width: 1320px)')
    const sync = () => setWide(query.matches)
    sync()
    query.addEventListener('change', sync)
    return () => query.removeEventListener('change', sync)
  }, [])

  useEffect(() => {
    if (!analyzing) return
    const timer = window.setInterval(() => setAnalyzeElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [analyzing])

  useEffect(() => {
    if (!generating) return
    const timer = window.setInterval(() => setGenElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [generating])

  // 生成中离开保护：页签关闭/刷新 + 应用内链接跳转（DESIGN §2.4）
  useEffect(() => {
    if (!generating) {
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
  }, [generating, pathname])

  const suggestions = useMemo(() => session?.suggestions ?? [], [session])
  const adoptedIds = useMemo(
    () => suggestions.filter((item) => states[item.id] === 'adopted').map((item) => item.id),
    [suggestions, states],
  )
  const pendingCount = suggestions.filter((item) => (states[item.id] ?? 'pending') === 'pending').length
  const adoptionKey = adoptedIds.join(',')
  const stale = full !== null && adoptionSnapshot !== null && adoptionKey !== adoptionSnapshot

  const visibleSuggestions =
    filter === 'pending'
      ? suggestions.filter((item) => (states[item.id] ?? 'pending') === 'pending')
      : suggestions

  const analyze = async (roleOverride: string | null) => {
    // 一次请求一个动作：生成中不再发第二次 AI 调用，避免重复扣费（DESIGN §4.8）
    if (profile === null || analyzing || generating) return
    const role = roleOverride === null || roleOverride.trim() === '' ? null : roleOverride.trim()
    setAnalyzing(true)
    setAnalyzeElapsed(0)
    setAnalyzeError(null)
    setFull(null)
    setGenError(null)
    setExportError(null)
    setChangedNotice(false)
    try {
      const response = await api.polishSuggestions(profile.resume_id, { target_role: role })
      if (!mountedRef.current) return
      const previous = new Map(
        suggestions.map((item) => [item.original_text, states[item.id] ?? 'pending'] as const),
      )
      const nextStates: Record<string, SuggestionState> = {}
      let lost = false
      response.suggestions.forEach((item) => {
        const carried = previous.get(item.original_text)
        nextStates[item.id] = carried ?? 'pending'
        if (previous.size > 0 && carried === undefined) lost = true
      })
      setSession({
        polishId: response.polish_id,
        resumeId: response.resume_id,
        targetRole: response.target_role,
        suggestions: response.suggestions,
        droppedCount: response.dropped_count,
        insufficientReason: response.insufficient_reason,
      })
      setStates(nextStates)
      setChangedNotice(lost)
      setFilter('all')
      setTab('polished')
    } catch (error) {
      if (!mountedRef.current) return
      // 失败只报错：已出建议与采纳状态都不清空（DESIGN §0.4）
      setAnalyzeError(errorMessage(error, '生成润色建议失败，请稍后重试'))
    } finally {
      if (mountedRef.current) setAnalyzing(false)
    }
  }

  const setSuggestionState = (id: string, next: SuggestionState) => {
    setStates((prev) => ({ ...prev, [id]: next }))
  }

  const generateFull = async () => {
    if (profile === null || session === null || generating || adoptedIds.length === 0) return
    setGenerating(true)
    setGenElapsed(0)
    setGenError(null)
    setExportError(null)
    try {
      const response = await api.polishFull(profile.resume_id, {
        polish_id: session.polishId,
        target_role: session.targetRole,
        suggestion_ids: adoptedIds,
      })
      if (!mountedRef.current) return
      setFull({
        markdown: response.markdown,
        droppedCount: response.dropped_count,
        regenerated: response.regenerated,
      })
      setAdoptionSnapshot(adoptionKey)
      setTab('polished')
    } catch (error) {
      if (!mountedRef.current) return
      setGenError(errorMessage(error, '生成成稿失败，请稍后重试'))
    } finally {
      if (mountedRef.current) setGenerating(false)
    }
  }

  const exportMarkdown = async () => {
    if (full === null || exporting) return
    setExporting(true)
    setExportError(null)
    try {
      const blob = new Blob([full.markdown], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = exportFileName()
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      window.setTimeout(() => URL.revokeObjectURL(url), 0)
      if (!mountedRef.current) return
      setToast((prev) => ({ message: EXPORT_TOAST_MESSAGE, seq: (prev?.seq ?? 0) + 1 }))
    } catch (error) {
      if (!mountedRef.current) return
      setExportError(errorMessage(error, '导出失败，请稍后重试'))
    } finally {
      if (mountedRef.current) setExporting(false)
    }
  }

  const resetRole = () => {
    const fallback = profile?.target_role ?? ''
    setRoleInput(fallback)
    if (session !== null) void analyze(null)
  }

  const profileMissing = profileAsync.error?.status === 404
  const profilePending = profileAsync.status !== 'success' && profileAsync.status !== 'error'
  const defaultRole = profile?.target_role ?? null
  const roleIsTemporary = session?.targetRole != null && session.targetRole !== defaultRole

  const showAside = wide || composeOpen
  const polishedText = full !== null ? full.markdown : buildPreview(suggestions, states)

  return (
    <section className="sc-polish-page">
      <header className="sc-page-header">
        <h1 className="sc-page-title">简历润色</h1>
        <p className="sc-page-sub">
          AI 只改措辞与结构，不改事实与数字；逐条对比后可采纳，成稿随时可导出
        </p>
      </header>

      {profilePending ? (
        <PhaseLoader title="正在读取画像" phases={['读取画像与目标岗位']} active={0} />
      ) : null}

      {!profilePending && profileMissing ? (
        <EmptyState
          reason="先上传简历，才能做润色：润色需要先有一份技术画像，才知道该按什么目标岗位改。"
          actionLabel="上传简历"
          actionTo="/"
        />
      ) : null}

      {!profilePending && !profileMissing && profileAsync.error !== null ? (
        <InlineError message={profileAsync.error.message} onRetry={profileAsync.reload} />
      ) : null}

      {!profilePending && profile !== null ? (
        <div className="sc-polish">
          <div className="sc-polish-main">
            <TargetRoleBar
              value={roleInput}
              defaultRole={defaultRole}
              busy={analyzing || generating}
              onChange={setRoleInput}
              onApply={() => void analyze(roleInput)}
              onReset={resetRole}
            />

            {analyzing ? (
              <PhaseLoader
                title={session === null ? '正在分析简历' : '正在按目标岗位重跑建议'}
                phases={ANALYSIS_PHASES}
                active={phaseOf(analyzeElapsed, ANALYSIS_STEP_S)}
                elapsedSec={analyzeElapsed}
              />
            ) : null}

            {analyzeError !== null && !analyzing ? (
              <InlineError
                message={analyzeError}
                onRetry={() => void analyze(roleInput)}
                retryLabel="重试"
              />
            ) : null}

            {session === null && !analyzing ? (
              <Card>
                <div className="sc-polish-guide">
                  <p className="sc-polish-guide-text">
                    点「开始分析」后，AI 会读一遍简历正文，逐条给出「原句 → 建议句 → 为什么这么改」，
                    并按目标岗位调整措辞。整段分析约 10–20 秒，建议可以重跑，成本可控。
                  </p>
                  <div className="sc-btn-row">
                    <Button onClick={() => void analyze(roleInput)}>开始分析</Button>
                    <span className="sc-meta-line">约 10–20 秒 · 不会自动扣额度</span>
                  </div>
                </div>
              </Card>
            ) : null}

            {session !== null ? (
              <div className="sc-polish-list">
                <div className="sc-polish-listhead">
                  <h2 className="sc-polish-listtitle">逐条建议（{suggestions.length} 条）</h2>
                  <div className="sc-polish-filters" role="group" aria-label="建议筛选">
                    <button
                      type="button"
                      className="sc-chip is-clickable"
                      aria-pressed={filter === 'all'}
                      onClick={() => setFilter('all')}
                    >
                      全部
                    </button>
                    <button
                      type="button"
                      className="sc-chip is-clickable"
                      aria-pressed={filter === 'pending'}
                      onClick={() => setFilter('pending')}
                    >
                      待处理 {pendingCount}
                    </button>
                  </div>
                  <span className="sc-polish-adopted-count">已采纳 {adoptedIds.length}</span>
                </div>

                {session.droppedCount > 0 ? (
                  <p className="sc-polish-warn">
                    {session.droppedCount} 条建议未通过事实校验，已丢弃
                  </p>
                ) : null}

                {session.insufficientReason ? (
                  <p className="sc-polish-note">{session.insufficientReason}</p>
                ) : null}

                {changedNotice ? (
                  <p className="sc-polish-note">建议已变化，请重新确认采纳状态</p>
                ) : null}

                {generating ? (
                  <p className="sc-polish-note">采纳/忽略仍可继续，但会在下次生成时生效</p>
                ) : null}

                {visibleSuggestions.length === 0 ? (
                  <p className="sc-polish-note">这批建议都处理完了，可以点「一键生成全篇润色版」。</p>
                ) : null}

                <div className="sc-polish-cards">
                  {visibleSuggestions.map((item) => (
                    <SuggestionCard
                      key={item.id}
                      suggestion={item}
                      state={states[item.id] ?? 'pending'}
                      busy={analyzing}
                      roleIsTemporary={roleIsTemporary}
                      onAdopt={() => setSuggestionState(item.id, 'adopted')}
                      onIgnore={() => setSuggestionState(item.id, 'ignored')}
                    />
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          {showAside ? (
            <aside className="sc-polish-aside" aria-label="成稿区">
              <SegTabs tabs={TAB_ITEMS} active={tab} onChange={(key) => setTab(key === 'original' ? 'original' : 'polished')} />

              <div id={`sc-seg-panel-${tab}`} role="tabpanel" aria-labelledby={`sc-seg-tab-${tab}`}>
                {tab === 'original' ? (
                  <ComposePreview
                    mode="preview"
                    meta="原版 · 逐字取自简历正文"
                    text={buildOriginal(suggestions)}
                    loading={false}
                    error={null}
                  />
                ) : (
                  <ComposePreview
                    mode={full !== null ? 'generated' : 'preview'}
                    text={polishedText}
                    loading={generating}
                    error={genError}
                    onRetry={() => void generateFull()}
                    phases={GENERATE_PHASES}
                    activePhase={phaseOf(genElapsed, GENERATE_STEP_S)}
                    elapsedSec={genElapsed}
                  />
                )}
              </div>

              {stale && !generating ? (
                <p className="sc-polish-note">采纳状态已变更，重新生成可更新成稿</p>
              ) : null}

              {full !== null && full.regenerated ? (
                <p className="sc-polish-note">服务端已按最新建议重新生成（缓存已失效）</p>
              ) : null}

              {full !== null && full.droppedCount > 0 ? (
                <p className="sc-polish-warn">成稿丢弃 {full.droppedCount} 条未通过校验的建议</p>
              ) : null}

              {exportError !== null ? (
                <InlineError message={exportError} onRetry={() => void exportMarkdown()} retryLabel="重新导出" />
              ) : null}

              <div className="sc-polish-actions">
                {full === null ? (
                  <>
                    <Button
                      onClick={() => void generateFull()}
                      loading={generating}
                      disabled={session === null || adoptedIds.length === 0}
                    >
                      一键生成全篇润色版
                    </Button>
                    <p className="sc-polish-hint">
                      {session === null
                        ? '先分析出建议，再生成成稿'
                        : adoptedIds.length === 0
                          ? '先采纳至少一条建议，再生成成稿'
                          : `已采纳 ${adoptedIds.length} 条 · 生成后导出取服务端文本`}
                    </p>
                  </>
                ) : (
                  <>
                    <div className="sc-btn-row">
                      <Button onClick={() => void exportMarkdown()} loading={exporting}>
                        导出 .md
                      </Button>
                      <Button variant="ghost" onClick={() => void generateFull()} disabled={generating}>
                        重新生成
                      </Button>
                    </div>
                    <p className="sc-polish-hint">导出文本与页面成稿同源（服务端 markdown，单源零变换）</p>
                  </>
                )}
              </div>
            </aside>
          ) : (
            <div className="sc-polish-toggle">
              <Button variant="secondary" onClick={() => setComposeOpen(true)}>
                成稿预览（{suggestions.length} 条建议已采纳 {adoptedIds.length}）
              </Button>
            </div>
          )}
        </div>
      ) : null}

      <ConfirmModal
        open={pendingLeave !== null}
        title="成稿生成中，离开会丢失本次采纳状态"
        message="成稿还在生成；离开本页后，本次的采纳与忽略状态不会保留，已生成的内容也不会带回。"
        confirmLabel="仍然离开"
        cancelLabel="留在本页"
        onConfirm={() => {
          const target = pendingLeave
          setPendingLeave(null)
          if (target !== null) navigate(target)
        }}
        onCancel={() => setPendingLeave(null)}
      />

      {toast ? (
        <Toast message={toast.message} seq={toast.seq} onClose={() => setToast(null)} />
      ) : null}
    </section>
  )
}
