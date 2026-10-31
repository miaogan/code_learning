import { Fragment, useState } from 'react'
import type { PolishSuggestion } from '../../api/types'
import { Button } from '../ui/Button'

export type SuggestionState = 'pending' | 'adopted' | 'ignored'

export interface SuggestionCardProps {
  suggestion: PolishSuggestion
  state: SuggestionState
  busy: boolean
  onAdopt: () => void
  onIgnore: () => void
  /** 该条建议是否来自临时岗位（来自本次重跑的目标岗位，非画像默认） */
  roleIsTemporary?: boolean
}

/** 缺数值处的占位符（AC-9 降级路径）：只渲染，不改文本。 */
const PLACEHOLDER = '〈待补充〉'
const CLAMP_CHARS = 96

const SECTION_LABEL: Record<PolishSuggestion['section'], string> = {
  project: '项目经历',
  experience: '工作经历',
  education: '教育背景',
  summary: '个人简介',
}

const NUMERIC_FLAG = 'numeric_added'

/** 把「〈待补充〉」渲染成 22 高虚线占位框，其它文本原样输出（零替换）。 */
function SuggestedText({ text }: { text: string }) {
  const parts = text.split(PLACEHOLDER)
  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={`${index}-${part.slice(0, 8)}`}>
          {index > 0 ? <span className="sc-sugg-placeholder">{PLACEHOLDER}</span> : null}
          {part}
        </Fragment>
      ))}
    </>
  )
}

/**
 * 建议卡：三段式（原句 / 建议句 / 为什么这么改）+ 采纳/忽略。
 * 整卡不可点（DESIGN §0.6 anti-pattern：误触率高，采纳只能点按钮）。
 */
export function SuggestionCard({
  suggestion,
  state,
  busy,
  onAdopt,
  onIgnore,
  roleIsTemporary = false,
}: SuggestionCardProps) {
  const [expanded, setExpanded] = useState(false)
  const degraded = suggestion.flags.includes(NUMERIC_FLAG)
  const clamped = !expanded && (suggestion.original_text.length > CLAMP_CHARS || suggestion.suggested_text.length > CLAMP_CHARS)

  const classes = ['sc-sugg-card']
  if (state === 'adopted') classes.push('is-adopted')
  if (state === 'ignored') classes.push('is-ignored')
  if (busy) classes.push('is-busy')

  return (
    <article className={classes.join(' ')} aria-busy={busy || undefined}>
      <div className="sc-sugg-meta">
        {degraded ? <span className="sc-sugg-flag">仅措辞建议</span> : null}
        <span className="sc-sugg-section">{SECTION_LABEL[suggestion.section]}</span>
        {suggestion.target_role ? (
          <span className="sc-sugg-role">
            目标岗位：{suggestion.target_role}
            {roleIsTemporary ? '（临时）' : ''}
          </span>
        ) : null}
      </div>

      <div className="sc-sugg-block">
        <p className="sc-sugg-label">原句</p>
        <p className={`sc-sugg-origin${clamped ? ' is-clamped' : ''}`}>
          {suggestion.original_text}
        </p>
      </div>

      {state === 'ignored' ? (
        <div className="sc-sugg-block">
          <p className="sc-sugg-label">建议句</p>
          <p className="sc-sugg-ignored">已忽略，成稿保留原句</p>
        </div>
      ) : (
        <div className="sc-sugg-block">
          <p className="sc-sugg-label">建议句</p>
          <p className={`sc-sugg-suggested${clamped ? ' is-clamped' : ''}`}>
            <SuggestedText text={suggestion.suggested_text} />
          </p>
        </div>
      )}

      <div className="sc-sugg-block">
        <p className="sc-sugg-label">为什么这么改</p>
        <p className="sc-sugg-reason">{suggestion.reason}</p>
      </div>

      {suggestion.original_text.length > CLAMP_CHARS || suggestion.suggested_text.length > CLAMP_CHARS ? (
        <button
          type="button"
          className="sc-sugg-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? '收起' : '展开全文'}
        </button>
      ) : null}

      <div className="sc-sugg-actions">
        <Button
          variant="secondary"
          aria-pressed={state === 'adopted'}
          disabled={busy}
          onClick={onAdopt}
        >
          {state === 'adopted' ? '✓ 已采纳' : '采纳'}
        </Button>
        <Button variant="ghost" disabled={busy} onClick={onIgnore}>
          {state === 'ignored' ? '✓ 已忽略' : '忽略'}
        </Button>
        <span className="sc-sugg-status" aria-live="polite">
          {state === 'adopted'
            ? '已采纳 · 将写进润色版'
            : state === 'ignored'
              ? '已忽略 · 成稿保留原句'
              : '待处理 · 未纳入成稿'}
        </span>
      </div>
    </article>
  )
}
