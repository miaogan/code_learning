import type { ChangeEvent, KeyboardEvent } from 'react'
import { Button } from '../ui/Button'
import { InlineError } from '../ui/InlineError'

/** 作答上限（沿用 r5 前的口径：0–800 字，超长由 maxlength 拦截，不做前端截断）。 */
export const MAX_ANSWER_CHARS = 800

/** 计时提示转警示色的阈值（DESIGN §0.3：≥13s 转 --warn）。 */
const ELAPSED_WARN_S = 13

export interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  /** 本轮评分中：按钮转「正在评分…」，textarea 只读（内容保留，AC-10） */
  submitting: boolean
  /** 其他阻塞（如恢复会话中）：textarea 与按钮都不可用 */
  disabled: boolean
  /** 会话已结束：整块只读态，不出现「下一题」类入口（AC-9） */
  readonly: boolean
  /** 本轮计时（秒），只影响提示行文案与颜色 */
  elapsedS: number
  /** 本轮错误（中文短句）：固定显示在输入区上方，不进入气泡流（AC-10） */
  error: string | null
}

/**
 * 页面底部粘性作答区（高 `--iq-composer-h`）：
 * textarea（最小 `--iq-input-h`，5 行封顶后框内滚动）+ 提示行 + 提交按钮。
 * Ctrl/Cmd + Enter 提交；Enter 只换行，避免误发（DESIGN §2.3「输入」）。
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  submitting,
  disabled,
  readonly,
  elapsedS,
  error,
}: ComposerProps) {
  const canSubmit = !readonly && !disabled && !submitting && value.trim().length > 0
  const seconds = Math.max(0, Math.floor(elapsedS))
  const metaClasses = ['sc-iq-meta']
  if (!readonly && seconds >= ELAPSED_WARN_S) metaClasses.push('is-warn')

  const handleChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    onChange(event.target.value)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault()
      if (canSubmit) onSubmit()
    }
  }

  const metaText = readonly
    ? '本场面试已结束 · 仅供回看'
    : `Ctrl/Cmd + Enter 提交 · 已用 ${seconds}s`

  return (
    <div className={`sc-iq-composer${readonly ? ' is-readonly' : ''}`}>
      {readonly ? <p className="sc-iq-readonly">本场面试已结束 · 输入区已关闭</p> : null}
      {error ? <InlineError message={error} onRetry={canSubmit ? onSubmit : undefined} retryLabel="重试本轮" /> : null}
      <textarea
        className="sc-iq-input"
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        readOnly={readonly || submitting}
        disabled={disabled}
        maxLength={MAX_ANSWER_CHARS}
        rows={3}
        placeholder={readonly ? '本场面试已结束' : '写下你的思路：先讲取舍，再讲落地细节（3–5 句即可）'}
        aria-label="你的回答"
        aria-readonly={readonly || submitting}
      />
      <div className="sc-iq-actions">
        <span className={metaClasses.join(' ')}>{metaText}</span>
        <Button onClick={onSubmit} disabled={!canSubmit} loading={submitting}>
          {submitting ? '正在评分…' : '提交回答'}
        </Button>
      </div>
    </div>
  )
}
