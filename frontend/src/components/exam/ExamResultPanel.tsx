import type { ExamQuestion, ExamResult } from '../../api/types'
import { formatElapsed } from '../../lib/format'
import { Card } from '../ui/Card'
import { RingProgress } from '../ui/RingProgress'

/**
 * 笔试出分面板（DESIGN §2.4 出分态）：总分环 56 / 档位文案 / 用时 / 客观题对题数 + 逐题复核。
 * 分数与用时只走 `lib/format.ts` 的格式化规则（与报告、Markdown 导出同规则）；
 * `✔`/`✗` 是符号 + 文字双通道，颜色不单独承载信息。
 */
export interface ExamResultPanelProps {
  result: ExamResult
  /** 本次试卷题目（按题号顺序渲染，保证 Q1→Qn 稳定不复用服务端顺序） */
  questions: ExamQuestion[]
}

const ANSWER_TRUNCATE = 40

function formatTotal(total: number): string {
  if (!Number.isFinite(total)) return '—'
  const rounded = Math.round(total * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

/** 0–100 三档（与得分环 >7 绿 / 4–7 黄 / <4 红的比例一致）。 */
function ringStateOf(total: number): 'success' | 'warn' | 'danger' {
  if (total >= 70) return 'success'
  if (total >= 40) return 'warn'
  return 'danger'
}

function tierText(total: number): string {
  if (total >= 85) return '基础扎实，可以挑战进阶方向'
  if (total >= 70) return '基础过关，个别方向待巩固'
  if (total >= 60) return '勉强达标，需要加强基础'
  return '需加强基础'
}

function displayAnswer(value: string[] | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '未作答'
  if (Array.isArray(value)) return value.length === 0 ? '未作答' : value.join('、')
  return value.length > ANSWER_TRUNCATE ? `${value.slice(0, ANSWER_TRUNCATE)}…` : value
}

export function ExamResultPanel({ result, questions }: ExamResultPanelProps) {
  const total = Number.isFinite(result.total) ? result.total : 0
  const byId = new Map(result.per_question.map((item) => [item.question_id, item]))

  return (
    <Card>
      <div className="sc-qcard">
        <div className="sc-score-side">
          <RingProgress
            size={56}
            stroke={5}
            value={total}
            max={100}
            label={String(Math.round(total))}
            state={ringStateOf(total)}
            ariaLabel={`笔试总分 ${formatTotal(total)} 分（满分 100）`}
          />
          <div className="sc-upload-summary">
            <p className="sc-file-name">
              <span className="sc-mono">{formatTotal(total)}</span>
              {' / 100 · '}
              {tierText(total)}
            </p>
            <p className="sc-qcard-hint">
              {`用时 ${formatElapsed(result.elapsed_s)} · 客观题答对 ${result.correct_count} / ${result.objective_total}`}
            </p>
          </div>
        </div>

        <div className="sc-upload-summary">
          <p className="sc-qcard-prompt">逐题复核</p>
          {questions.map((question, index) => {
            const graded = byId.get(question.id)
            const correct = graded?.correct
            if (correct === true) {
              return (
                <p key={question.id} className="sc-meta-line">
                  <span className="sc-mono">{`Q${index + 1}`}</span>
                  <span className="sc-delta-up">✔ 正确</span>
                  <span>{`你的选择 ${displayAnswer(graded?.your_answer)}`}</span>
                </p>
              )
            }
            if (correct === false) {
              return (
                <p key={question.id} className="sc-meta-line">
                  <span className="sc-mono">{`Q${index + 1}`}</span>
                  <span className="sc-delta-down">✗ 错误</span>
                  <span>{`你的选择 ${displayAnswer(graded?.your_answer)}`}</span>
                  <span>{`正确答案 ${displayAnswer(graded?.correct_answer)}`}</span>
                </p>
              )
            }
            return (
              <p key={question.id} className="sc-meta-line">
                <span className="sc-mono">{`Q${index + 1}`}</span>
                <span>· 简答，不计入客观分</span>
              </p>
            )
          })}
        </div>
      </div>
    </Card>
  )
}
