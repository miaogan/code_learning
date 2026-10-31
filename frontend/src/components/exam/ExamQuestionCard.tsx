import type { ExamQuestion, PerQuestionResult } from '../../api/types'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'

/**
 * 笔试题目卡：单选 / 多选 / 简答三型共用一张卡（DESIGN §2.4）。
 * 选项行用原生 radio / checkbox（`base.css` 已对 `.sc-opt input` 定过 1em 尺寸），因此键盘与读屏天然可用。
 * 传 `review` 即切复核态：`.sc-opt.is-correct/.is-wrong` 着色 + 头部 ✔/✗ 文字；传 `locked` 为提交中锁定。
 * 组件不发请求、不 import api（TECHNICAL §3.2 硬规则 1）。
 */
export interface ExamQuestionCardProps {
  /** 题目序号，从 0 开始，渲染为 Q1 */
  index: number
  question: ExamQuestion
  /** 单选 / 多选为选项 key 数组，简答为字符串 */
  value: string[] | string
  onChange: (value: string[] | string) => void
  /** 复核态（判分后传入）：只读 + 正确/错误着色 */
  review?: PerQuestionResult | null
  /** 提交中：只读但仍展示已选内容（不清空作答） */
  locked?: boolean
}

const KIND_LABEL: Record<ExamQuestion['kind'], string> = {
  single: '单选',
  multiple: '多选',
  text: '简答',
}

/** 把「key 数组 / 简答文本 / null」统一看成 key 集合。 */
function keysOf(value: string[] | string | null | undefined): string[] {
  if (value === null || value === undefined) return []
  if (Array.isArray(value)) return value
  return value === '' ? [] : [value]
}

function displayAnswer(value: string[] | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '未作答'
  if (Array.isArray(value)) return value.length === 0 ? '未作答' : value.join('、')
  return value
}

/** 简答长文本在复核行里截断，避免撑破窄栏。 */
function truncate(text: string, max = 60): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

export function ExamQuestionCard({
  index,
  question,
  value,
  onChange,
  review = null,
  locked = false,
}: ExamQuestionCardProps) {
  const disabled = locked || review !== null
  const mine = keysOf(value)
  const correctKeys = question.kind === 'text' ? [] : keysOf(review?.correct_answer)
  const correct = review?.correct

  const toggle = (key: string) => {
    if (disabled) return
    if (question.kind === 'multiple') {
      const next = mine.includes(key) ? mine.filter((k) => k !== key) : [...mine, key].sort()
      onChange(next)
      return
    }
    onChange([key])
  }

  const markText =
    review === null ? null : correct === true ? '✔ 正确' : correct === false ? '✗ 错误' : '· 已提交'

  return (
    <Card className="sc-qcard">
      <div className="sc-qcard-head">
        <span className="sc-mono">{`Q${index + 1}`}</span>
        <Chip label={KIND_LABEL[question.kind]} />
        {question.direction ? <Chip label={question.direction} tone="direction" /> : null}
        {markText ? (
          <span
            className={
              correct === true ? 'sc-delta-up' : correct === false ? 'sc-delta-down' : undefined
            }
          >
            {markText}
          </span>
        ) : null}
      </div>

      <p className="sc-qcard-prompt">{question.prompt}</p>

      {question.kind === 'text' ? (
        review !== null ? (
          <div className="sc-qcard-hint">
            <p>你的作答：{truncate(displayAnswer(value))}</p>
            <p>参考答案：{displayAnswer(review.correct_answer) || '本卷未记录'}</p>
          </div>
        ) : (
          <textarea
            value={Array.isArray(value) ? '' : value}
            onChange={(event) => onChange(event.target.value)}
            placeholder="写下你的思路（简答题不计入客观题数）"
            aria-label={`第 ${index + 1} 题作答`}
            disabled={disabled}
          />
        )
      ) : (
        <div className="sc-upload-summary">
          {question.options.map((option) => {
            const selected = mine.includes(option.key)
            const isCorrect = review !== null && correctKeys.includes(option.key)
            const isWrong = review !== null && selected && !correctKeys.includes(option.key)
            const classes = ['sc-opt']
            if (isCorrect) classes.push('is-correct')
            else if (isWrong) classes.push('is-wrong')
            else if (selected) classes.push('is-selected')

            return (
              <label
                key={option.key}
                className={classes.join(' ')}
                aria-disabled={disabled || undefined}
              >
                <input
                  type={question.kind === 'multiple' ? 'checkbox' : 'radio'}
                  name={`exam-${question.id}`}
                  checked={selected}
                  disabled={disabled}
                  onChange={() => toggle(option.key)}
                />
                <span className="sc-opt-key">{option.key}</span>
                <span className="sc-opt-text">{option.text}</span>
              </label>
            )
          })}
        </div>
      )}
    </Card>
  )
}
