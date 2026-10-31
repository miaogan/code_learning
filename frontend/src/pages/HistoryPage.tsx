import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { TimelineSection } from '../components/history/TimelineSection'
import { TrendTable } from '../components/history/TrendTable'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { useAsync } from '../lib/useAsync'

/** 历史条数：后端 `Query(ge=1, le=50)`，取 10 条足够对比最近几轮（AC-10 要求 ≥3）。 */
const HISTORY_LIMIT = 10

/**
 * 成绩趋势（AC-10）：最近 10 次面试/笔试的分数、短板条数与「与同类型上一次」的差值。
 * 数据全部来自 `GET /api/history`（服务端投影 + 服务端排序），页面不做二次统计与二次排序；
 * 分数量纲不同（面试均分 /10、笔试总分 /100），故对比只在同类型之间发生（口径由 TrendTable 负责）。
 */
export default function HistoryPage() {
  const historyAsync = useAsync(() => api.history(HISTORY_LIMIT), [])
  const rows = historyAsync.data

  const loading = historyAsync.status === 'loading' && rows === null
  const isEmpty = rows !== null && rows.length === 0
  const interviewCount = rows === null ? 0 : rows.filter((row) => row.kind === 'interview').length
  const examCount = rows === null ? 0 : rows.filter((row) => row.kind === 'exam').length

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">成绩趋势</h1>
        <p className="sc-page-sub">
          {`最近 ${HISTORY_LIMIT} 次测评的面试均分、笔试总分与短板条数，按时间倒序；变化列只与同类型上一次对比`}
        </p>
      </header>

      {loading ? <PhaseLoader title="正在读取本机历史记录" phases={['读取已完成的测评']} active={0} /> : null}

      {historyAsync.status === 'error' && historyAsync.error ? (
        <InlineError message={historyAsync.error.message} onRetry={historyAsync.reload} />
      ) : null}

      {isEmpty ? (
        <EmptyState
          reason="完成一次测评后，这里会出现你的成绩趋势 —— 可以对比前后两次是否真的补上了短板。"
          actionLabel="开始测评"
          actionTo="/exam"
        />
      ) : null}

      {rows !== null && rows.length > 0 ? (
        <>
          <p className="sc-meta-line">
            <span>{`共 ${rows.length} 次`}</span>
            <span>{`面试 ${interviewCount} 次`}</span>
            <span>{`笔试 ${examCount} 次`}</span>
            <span>时间倒序</span>
          </p>

          <Card>
            <TrendTable rows={rows} />
          </Card>

          <p className="sc-meta-line">
            ↑ 高于上一次同类测评、↓ 低于上一次同类测评；同类不足两次时显示「暂无对比」，每次得分相同时显示「持平」。
          </p>

          <div className="sc-btn-row">
            <Link className="sc-btn sc-btn--primary" to="/exam">
              再测一轮笔试
            </Link>
            <Button
              variant="secondary"
              onClick={historyAsync.reload}
              disabled={historyAsync.status === 'loading'}
            >
              重新读取
            </Button>
          </div>
        </>
      ) : null}

      {/* 成长时间线（AC-4/5）：内嵌在趋势表下方，自带三态 —— 它失败时趋势表照常显示。 */}
      <TimelineSection runRows={rows} />
    </section>
  )
}
