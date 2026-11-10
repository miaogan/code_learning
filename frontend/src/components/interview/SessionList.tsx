import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { InterviewSessionSummary } from '../../api/types'
import { formatScore, formatWhen } from '../../lib/format'
import { useAsync } from '../../lib/useAsync'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'

/** 列表条数：最近 8 场足够回答「我上次答到哪了」，更长历史交给成绩趋势页。 */
const LIMIT = 8

/** 一行副文案：目标岗位 · 已答题数 · 均分（均分缺失时不补 0，直接省略）。 */
function describe(row: InterviewSessionSummary): string {
  const parts: string[] = []
  if (row.settings !== null && row.settings.target_role !== '') parts.push(row.settings.target_role)
  parts.push(`已答 ${row.answered_count}/${row.total} 题`)
  if (row.interview_avg !== null) parts.push(`均分 ${formatScore(row.interview_avg)}/10`)
  return parts.join(' · ')
}

/**
 * 历史面试列表（r62）：列出本账号最近几场（**含未完成场次**），
 * 点进去复用 `?run_id=` 的会话恢复 —— 在途接着答、已完成只读回放。
 * 列表只是入口，读数全部来自 `GET /api/interviews`（不在前端二次统计）。
 */
export function SessionList() {
  const sessions = useAsync((signal) => api.listInterviews(LIMIT, signal), [])
  const rows = sessions.data ?? []

  // 首次加载不占位（配置表单在上方，列表是补充信息，避免闪一下空标题）。
  if (sessions.status === 'loading' && sessions.data === null) return null

  if (sessions.status === 'error') {
    return (
      <section className="sc-iq-sessions" aria-label="历史面试">
        <p className="sc-iq-meta">
          历史面试读取失败，不影响开始新一场。
          <Button variant="ghost" onClick={sessions.reload}>
            重试
          </Button>
        </p>
      </section>
    )
  }

  if (rows.length === 0) return null

  return (
    <section className="sc-iq-sessions" aria-label="历史面试">
      <div className="sc-iq-sessions-head">
        <h2 className="sc-iq-sessions-title">历史面试</h2>
        <p className="sc-iq-meta">{`最近 ${rows.length} 场 · 未完成的可以接着答，已完成的只读回放`}</p>
      </div>
      <ul className="sc-iq-sessions-list">
        {rows.map((row) => {
          const completed = row.status === 'completed'
          return (
            <li className="sc-iq-session" key={row.run_id}>
              <div className="sc-iq-session-top">
                <Chip label={completed ? '已完成' : '未完成'} tone="direction" />
                <span className="sc-mono">{formatWhen(row.created_at)}</span>
              </div>
              <p className="sc-iq-session-sub">{describe(row)}</p>
              <Link
                className="sc-plan-taskgo"
                to={`/interview?run_id=${encodeURIComponent(row.run_id)}`}
                aria-label={`${completed ? '回放' : '继续'} ${formatWhen(row.created_at)} 的模拟面试`}
              >
                {completed ? '回放复盘 →' : '继续作答 →'}
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
