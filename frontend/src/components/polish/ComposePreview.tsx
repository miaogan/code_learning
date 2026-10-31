import { InlineError } from '../ui/InlineError'
import { PhaseLoader } from '../ui/PhaseLoader'

export interface ComposePreviewProps {
  /** preview = 本地切片预览（未生成）；generated = 服务端成稿（单源，导出取此文本） */
  mode: 'preview' | 'generated'
  text: string
  loading: boolean
  error: string | null
  onRetry?: () => void
  /** 生成阶段文案（可选：未传时用默认三段） */
  phases?: string[]
  /** 当前阶段下标（可选） */
  activePhase?: number
  /** 已用秒数（可选，>20 由页面追加「仍在生成」提示） */
  elapsedSec?: number
  /** 覆盖顶部 meta 文案（原版 Tab 等非生成场景） */
  meta?: string
}

const DEFAULT_PHASES = ['汇总已采纳条目', '重写段落', '拼装成稿']
const EMPTY_PREVIEW = '还没有可预览的内容：先在左侧采纳建议，或点「一键生成全篇润色版」由服务端生成成稿。'

/** Markdown 轻渲染：标题 / 列表 / 段落。文本本身不做任何裁剪与替换（导出仍取原始 markdown）。 */
function renderMarkdown(text: string) {
  const lines = text.split('\n')
  return lines.map((line, index) => {
    const key = `${index}-${line.slice(0, 12)}`
    if (line.startsWith('### ') || line.startsWith('## ') || line.startsWith('# ')) {
      const content = line.replace(/^#+\s+/, '')
      return (
        <p key={key} className="sc-compose-line sc-compose-heading">
          {content}
        </p>
      )
    }
    if (line.startsWith('- ') || line.startsWith('* ')) {
      return (
        <p key={key} className="sc-compose-line sc-compose-bullet">
          {line.slice(2)}
        </p>
      )
    }
    if (line.trim() === '') {
      return <p key={key} className="sc-compose-line sc-compose-blank" aria-hidden="true" />
    }
    return (
      <p key={key} className="sc-compose-line">
        {line}
      </p>
    )
  })
}

/** 成稿区：预览与成稿两种真源在同一组件内，用 meta 文案区分（DESIGN §2.4）。 */
export function ComposePreview({
  mode,
  text,
  loading,
  error,
  onRetry,
  phases = DEFAULT_PHASES,
  activePhase = 0,
  elapsedSec,
  meta: metaOverride,
}: ComposePreviewProps) {
  const meta = metaOverride ?? (loading
    ? '正在生成成稿'
    : mode === 'generated'
      ? '已生成 · 导出取此文本（单源）'
      : '预览 · 未生成')

  return (
    <div className="sc-compose">
      <p className="sc-compose-meta">{meta}</p>
      {loading ? (
        <div className="sc-compose-state">
          <PhaseLoader phases={phases} active={activePhase} elapsedSec={elapsedSec} />
          {typeof elapsedSec === 'number' && elapsedSec > 20 ? (
            <p className="sc-compose-slow">
              仍在生成 · 已用 {elapsedSec}s；已采纳的条目不会丢失
            </p>
          ) : null}
        </div>
      ) : null}

      {!loading && error ? (
        <div className="sc-compose-state">
          <InlineError message={error} onRetry={onRetry} retryLabel="重试" />
        </div>
      ) : null}

      {!loading && !error ? (
        <div
          className="sc-compose-body"
          tabIndex={0}
          role="region"
          aria-label={mode === 'generated' ? '成稿全文' : '成稿预览'}
        >
          {text.trim() === '' ? (
            <p className="sc-compose-empty">{EMPTY_PREVIEW}</p>
          ) : (
            renderMarkdown(text)
          )}
        </div>
      ) : null}
    </div>
  )
}
