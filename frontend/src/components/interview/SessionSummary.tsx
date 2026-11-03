import { Link } from 'react-router-dom'
import type { InterviewSessionQuestion, InterviewSettings } from '../../api/types'
import { formatScore } from '../../lib/format'
import { Button } from '../ui/Button'
import { RingProgress } from '../ui/RingProgress'
import { scoreRingState } from './ScoreBadge'
import { averageOf, kindAverageOf, type QuestionKind } from './chatModel'

const KINDS: QuestionKind[] = ['technical', 'project', 'challenge']

const KIND_LABEL: Record<QuestionKind, string> = {
  technical: '技术题',
  project: '项目深挖',
  challenge: '进阶',
}

export interface SessionSummaryProps {
  /** 本场 run id：报告入口据此只汇总这一场，避免混入无关旧场次。 */
  runId: string
  questions: InterviewSessionQuestion[]
  /** 仅用于「重开一场」的语义提示；本场设定文本的唯一格式化入口是 SettingsBar.settingsLine */
  settings: InterviewSettings | null
  onRestart: () => void
}

/**
 * 结束态汇总块（DESIGN §2.4）：56 环均分 + 分类均分 + 双 CTA。
 * 均分环沿用 `scoreRingState` 三档色且环内有数字（颜色永不单独承载信息）。
 */
export function SessionSummary({ runId, questions, settings, onRestart }: SessionSummaryProps) {
  const scores = questions
    .map((question) => question.score)
    .filter((score): score is number => typeof score === 'number')
  const answered = scores.length
  const avg = averageOf(scores)

  return (
    <section className="sc-iq-summary" aria-label="本场面试汇总">
      <div className="sc-iq-summary-head">
        <RingProgress
          size={56}
          stroke={5}
          value={avg}
          max={10}
          label={formatScore(avg)}
          state={scoreRingState(avg)}
          ariaLabel={`本场均分 ${formatScore(avg)} 分，满分 10 分`}
        />
        <div className="sc-iq-summary-nums">
          <p className="sc-iq-summary-avg">本场均分 {formatScore(avg)} / 10</p>
          <p className="sc-iq-summary-sub">已答 {answered} 题 · 每题 0–10 分</p>
        </div>
      </div>

      <p className="sc-iq-summary-kinds">
        {KINDS.map((kind) => {
          const count = questions.filter(
            (question) => question.kind === kind && typeof question.score === 'number',
          ).length
          const value = count > 0 ? formatScore(kindAverageOf(questions, kind)) : '—'
          return (
            <span key={kind} className="sc-iq-summary-kind">
              {KIND_LABEL[kind]} {value}
            </span>
          )
        })}
      </p>

      <p className="sc-iq-summary-note">短板与课程由诊断报告统一给出。</p>

      <div className="sc-iq-summary-actions">
        <Link
          className="sc-btn sc-btn--primary"
          to={`/report?run_ids=${encodeURIComponent(runId)}`}
        >
          去看诊断报告
        </Link>
        <Button variant="secondary" onClick={onRestart}>
          重开一场
        </Button>
      </div>

      <p className="sc-iq-summary-hint">
        {settings ? '重开一场将沿用本场设定，可再修改' : '重开一场需重新填写本场设定'}
      </p>
    </section>
  )
}
