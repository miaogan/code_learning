import { useMemo } from 'react'
import { ApiError, api } from '../../api/client'
import type { InterviewSession, InterviewSessionQuestion } from '../../api/types'
import { formatScore } from '../../lib/format'
import { useAsync } from '../../lib/useAsync'
import { Card } from '../ui/Card'
import { InlineError } from '../ui/InlineError'

export interface AnswerReviewProps {
  /** 本场报告的测评 id：逐个读面试会话，非面试 run 的失败直接忽略。 */
  runIds: string[]
}

const KIND_LABEL: Record<InterviewSessionQuestion['kind'], string> = {
  technical: '技术题',
  project: '项目题',
  challenge: '追问',
}

const REVIEW_ERROR_MESSAGE = '面试作答记录读取失败，可稍后重试'
const REVIEW_LOADING_MESSAGE = '正在读取本场面试的逐题作答…'

interface ReviewSession {
  session: InterviewSession
  /** 原始题号 + 题目：只保留真正作答过的题（未作答不构成复盘素材）。 */
  answered: { index: number; question: InterviewSessionQuestion }[]
}

async function loadSessions(runIds: string[], signal: AbortSignal): Promise<InterviewSession[]> {
  const settled = await Promise.allSettled(runIds.map((runId) => api.getInterview(runId, signal)))
  return settled
    .filter(
      (result): result is PromiseFulfilledResult<InterviewSession> => result.status === 'fulfilled',
    )
    .map((result) => result.value)
}

function errorMessage(error: ApiError | null): string {
  return error?.message ? error.message : REVIEW_ERROR_MESSAGE
}

/**
 * 「逐题复盘」（调研改造 1 · 对标 BOSS 直聘 AI 模拟面试报告）。
 *
 * 练完必给报告：报告页不只给结论，还把本场每道面试题的回答、得分、点评与思路提示并排回放。
 * 数据全部来自 `GET /api/interviews/{run_id}` 的真实会话，前端不重算分数、不补写点评。
 * 报告只含笔试 run 或会话里没有作答时整块隐藏（不渲染空卡）。
 */
export function AnswerReview({ runIds }: AnswerReviewProps) {
  const key = runIds.join(',')
  const reviewAsync = useAsync((signal) => loadSessions(runIds, signal), [key])

  const sessions = useMemo<ReviewSession[]>(() => {
    const loaded = reviewAsync.data ?? []
    return loaded
      .map((session) => ({
        session,
        answered: session.questions
          .map((question, index) => ({ index, question }))
          .filter(
            (entry) =>
              entry.question.answer !== null && entry.question.answer.trim() !== '',
          ),
      }))
      .filter((entry) => entry.answered.length > 0)
  }, [reviewAsync.data])

  if (reviewAsync.status === 'error') {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">逐题复盘</h3>
        </div>
        <InlineError
          message={errorMessage(reviewAsync.error)}
          onRetry={reviewAsync.reload}
          retryLabel="重新读取"
        />
      </Card>
    )
  }

  if (reviewAsync.data === null) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">逐题复盘</h3>
        </div>
        <p className="sc-coach-note">{REVIEW_LOADING_MESSAGE}</p>
      </Card>
    )
  }

  if (sessions.length === 0) return null

  return (
    <Card className="sc-coach-block">
      <div className="sc-coach-blockhead">
        <h3 className="sc-coach-blocktitle">逐题复盘</h3>
        <p className="sc-coach-meta">按作答顺序回看每道题的回答、点评与思路提示</p>
      </div>

      {sessions.map(({ session, answered }, sessionIndex) => (
        <div className="sc-review-group" key={session.run_id}>
          {sessions.length > 1 ? (
            <p className="sc-coach-meta">
              {`第 ${sessionIndex + 1} 场面试 · 已答 ${answered.length} / ${session.total} 题` +
                (session.interview_avg === null
                  ? ''
                  : ` · 均分 ${formatScore(session.interview_avg)}`)}
            </p>
          ) : null}

          {answered.map(({ index, question }) => (
            <article className="sc-review-item" key={question.id}>
              <div className="sc-review-head">
                <span className="sc-mono">{`Q${index + 1}`}</span>
                <span className="sc-chip">{KIND_LABEL[question.kind]}</span>
                <span className="sc-review-score sc-mono">
                  {question.score === null ? '未评分' : `${formatScore(question.score)} / 10`}
                </span>
              </div>
              <p className="sc-review-prompt">{question.prompt}</p>

              <div className="sc-review-field">
                <p className="sc-review-label">我的回答</p>
                <p className="sc-review-text">{question.answer}</p>
              </div>

              {question.comment !== null && question.comment.trim() !== '' ? (
                <div className="sc-review-field">
                  <p className="sc-review-label">点评</p>
                  <p className="sc-review-text">{question.comment}</p>
                </div>
              ) : null}

              {question.hint !== '' ? (
                <div className="sc-review-field">
                  <p className="sc-review-label">思路提示</p>
                  <p className="sc-review-text is-hint">{question.hint}</p>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ))}
    </Card>
  )
}
