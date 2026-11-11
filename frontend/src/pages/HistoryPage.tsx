import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { TimelineSection } from '../components/history/TimelineSection'
import { TrendChart } from '../components/history/TrendChart'
import { TrendTable } from '../components/history/TrendTable'
import { SegTabs } from '../components/polish/SegTabs'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { Pagination } from '../components/ui/Pagination'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { useAsync } from '../lib/useAsync'

/** 每页条数：后端 `limit`（1..50），一页 10 次足够对比最近几轮，再往前翻页看更早的。 */
const PAGE_SIZE = 10

type KindFilter = 'all' | 'interview' | 'exam'

const FILTER_TABS = [
  { key: 'all', label: '全部' },
  { key: 'interview', label: '面试' },
  { key: 'exam', label: '笔试' },
]

/**
 * 成绩趋势（AC-10）：面试/笔试的分数、短板条数与「与同类型上一次」的差值。
 * 数据全部来自 `GET /api/history`（服务端投影 + 排序 + 类型筛选 + 分页），页面不做二次统计；
 * 分数量纲不同（面试均分 /10、笔试总分 /100），对比只在同类型之间发生（口径由服务端算好、
 * TrendTable 只负责展示，翻页后页首行的对比对象落在上一页也不会失真）。
 */
export default function HistoryPage() {
  const [kindFilter, setKindFilter] = useState<KindFilter>('all')
  const [page, setPage] = useState(1)
  const historyAsync = useAsync(
    () =>
      api.history({
        limit: PAGE_SIZE,
        page,
        kind: kindFilter === 'all' ? undefined : kindFilter,
      }),
    [page, kindFilter],
  )
  const data = historyAsync.data
  const rows = data === null ? null : data.items
  const total = data === null ? 0 : data.total
  const interviewCount = data === null ? 0 : data.interview_total
  const examCount = data === null ? 0 : data.exam_total

  const loading = historyAsync.status === 'loading' && data === null
  const isEmpty = kindFilter === 'all' && data !== null && total === 0

  const changeFilter = (key: string): void => {
    setKindFilter(key === 'interview' || key === 'exam' ? key : 'all')
    setPage(1)
  }

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">战绩</h1>
        <p className="sc-page-sub">
          每页 {PAGE_SIZE} 次测评的面试均分、笔试总分与短板条数，按时间倒序；
          变化列只与同类型上一次对比
        </p>
      </header>

      {loading ? (
        <PhaseLoader title="正在读取本机历史记录" phases={['读取已完成的测评']} active={0} />
      ) : null}

      {historyAsync.status === 'error' && historyAsync.error ? (
        <InlineError message={historyAsync.error.message} onRetry={historyAsync.reload} />
      ) : null}

      {isEmpty ? (
        <>
          <EmptyState
            reason="完成一次测评后，这里会出现你的战绩 —— 可以对比前后两次是否真的补上了短板。"
            actionLabel="开始测评"
            actionTo="/exam"
          />
          {/* 旁路（r27）：测评依赖画像，没上传简历的用户点「开始测评」只会撞到门禁，
              这里直接把上传与免画像出口摆在同一屏，省掉一跳。 */}
          <div className="sc-btn-row">
            <p className="sc-meta-line">还没上传简历？测评前需要先有画像：</p>
            <Link className="sc-btn sc-btn--secondary" to="/">
              去上传简历
            </Link>
            <Link className="sc-btn sc-btn--secondary" to="/practice">
              先去练习
            </Link>
          </div>
        </>
      ) : null}

      {data !== null && total > 0 ? (
        <>
          <SegTabs tabs={FILTER_TABS} active={kindFilter} onChange={changeFilter} ariaLabel="成绩类型筛选" />

          <p className="sc-meta-line">
            <span>{`共 ${total} 次`}</span>
            <span>{`面试 ${interviewCount} 次`}</span>
            <span>{`笔试 ${examCount} 次`}</span>
            <span>时间倒序</span>
          </p>

          {rows !== null && rows.length > 0 ? (
            <>
              <TrendChart rows={rows} />
              <Card>
                <TrendTable rows={rows} />
              </Card>
              <Pagination
                page={page}
                pageSize={PAGE_SIZE}
                total={total}
                onChange={setPage}
                label="成绩记录分页"
              />
            </>
          ) : (
            <p className="sc-meta-line">该类型还没有已完成记录，做一次后会出现在这里。</p>
          )}

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
