import { useEffect, useRef } from 'react'
import type { ChangeEvent, KeyboardEvent } from 'react'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { InlineError } from '../ui/InlineError'
import { ScoreBadge } from './ScoreBadge'
import type { InterviewQuestion, ScoreResult } from '../../api/types'

/** 作答上限（DESIGN §2.3：textarea 128 / 0–800 字）。 */
export const MAX_ANSWER_CHARS = 800

/** 题目类型文案：技术题 / 项目深挖 为中性，挑战题为「进阶」并用 --warn 标注（总量 ≤20%，DESIGN §2.3）。 */
export const QUESTION_KIND_LABEL: Record<InterviewQuestion['kind'], string> = {
  technical: '技术题',
  project: '项目深挖',
  challenge: '进阶',
}

export interface QuestionCardProps {
  index: number
  total: number
  question: InterviewQuestion
  answer: string
  /** 非 null 即已答态：同卡出分，textarea 仍在位（不卸载内容，AC-3） */
  score: ScoreResult | null
  submitting: boolean
  errorMessage?: string
  onAnswerChange: (value: string) => void
  onSubmit: () => void
  onRetry?: () => void
}

/**
 * 题卡：题面 + 作答建议 + textarea(128) + 提交；得分环与点评出现在同一卡内。
 * 已答态只读展示，作答文本永不清空（评分失败/超时后可直接重试）。
 */
export function QuestionCard({
  index,
  total,
  question,
  answer,
  score,
  submitting,
  errorMessage,
  onAnswerChange,
  onSubmit,
  onRetry,
}: QuestionCardProps) {
  const titleRef = useRef<HTMLHeadingElement>(null)
  const answered = score !== null

  // 逐题切换后焦点落到新题卡标题（DESIGN §0.6 / §5 键盘可达）。
  useEffect(() => {
    const node = titleRef.current
    if (!node) return
    node.focus({ preventScroll: true })
    node.scrollIntoView({ block: 'start' })
  }, [question.id])

  const handleChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    onAnswerChange(event.target.value)
  }

  // Ctrl/Cmd+Enter 提交，避免 Enter 换行时误提交（DESIGN §2.3「键盘」）。
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault()
      if (!answered && !submitting && answer.trim().length > 0) onSubmit()
    }
  }

  const canSubmit = !answered && !submitting && answer.trim().length > 0

  return (
    <Card className="sc-qcard" active={!answered}>
      <div className="sc-qcard-head">
        <Chip label={`Q${index + 1}`} />
        {question.kind === 'challenge' ? (
          <span className="sc-badge sc-badge--medium">进阶</span>
        ) : (
          <Chip label={QUESTION_KIND_LABEL[question.kind]} tone="direction" />
        )}
        <span className="sc-meta-line">
          第 {index + 1} / {total} 题{answered ? ' · 已出分' : ''}
        </span>
      </div>

      <h2 ref={titleRef} className="sc-qcard-prompt" tabIndex={-1}>
        {question.prompt}
      </h2>
      <p className="sc-qcard-hint">{question.hint}</p>

      <textarea
        value={answer}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        readOnly={answered}
        disabled={submitting}
        maxLength={MAX_ANSWER_CHARS}
        rows={5}
        aria-label={`第 ${index + 1} 题作答`}
        aria-readonly={answered}
        placeholder="写下你的思路：先讲取舍，再讲落地细节（3–5 句即可）"
      />

      <div className="sc-meta-line">
        <span>
          {answer.length} / {MAX_ANSWER_CHARS} 字
        </span>
        <span>
          {answered
            ? '已提交，可点「重新作答」修改'
            : submitting
              ? '正在评分，请稍候'
              : 'Ctrl / ⌘ + Enter 提交'}
        </span>
      </div>

      {errorMessage ? <InlineError message={errorMessage} onRetry={onRetry} /> : null}

      {score ? <ScoreBadge score={score.score} comment={score.comment} /> : null}

      {!answered ? (
        <div className="sc-btn-row">
          <Button onClick={onSubmit} loading={submitting} disabled={!canSubmit}>
            {submitting ? '评分中' : '提交并评分'}
          </Button>
        </div>
      ) : null}
    </Card>
  )
}
