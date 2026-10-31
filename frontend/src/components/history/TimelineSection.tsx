import { api } from '../../api/client'
import type { RunSummary, TimelineEvent as TimelineEventData } from '../../api/types'
import { useAsync } from '../../lib/useAsync'
import { EmptyState } from '../ui/EmptyState'
import { InlineError } from '../ui/InlineError'
import { PhaseLoader } from '../ui/PhaseLoader'
import { TimelineEvent } from './TimelineEvent'

export interface TimelineSectionProps {
  /**
   * 同页趋势表的行（`GET /api/history` 结果；`null` = 尚未取得）。
   * 只用于**派生**「有 N 次测评未能记入成长记忆」提示（DESIGN §4-5：事件数 < 趋势表行数），
   * 不参与排序、不做二次统计 —— 排序与指标口径都在服务端。
   */
  runRows: RunSummary[] | null
  /** 与 `GET /api/timeline` 的 `limit`（后端 `ge=1, le=50`，默认 20）。 */
  limit?: number
}

const DEFAULT_LIMIT = 20

/** 「测评事件」= 面试 / 笔试；简历事件不计入趋势表行数的对比（趋势表只含测评）。 */
function isRunEvent(event: TimelineEventData): boolean {
  return event.type === 'interview' || event.type === 'exam'
}

/**
 * 成长时间线区（AC-4 / AC-5）：内嵌 `/history`，位于趋势表之下。
 *
 * - 数据源只有 `GET /api/timeline`（服务端已倒序 + 已算好 `comparison`），页面零计算零排序；
 * - 自己持有 `useAsync` 三态，因此**时间线失败不会隐藏趋势表**（两者互不阻塞）；
 * - 首条事件加 `latest` 强调；空态/失败/加载分别为 EmptyState / InlineError / PhaseLoader。
 */
export function TimelineSection({ runRows, limit = DEFAULT_LIMIT }: TimelineSectionProps) {
  const timelineAsync = useAsync((signal) => api.timeline(limit, signal), [limit])
  const events = timelineAsync.data

  const succeeded = timelineAsync.status === 'success' && events !== null
  const loading = timelineAsync.status === 'loading' && events === null
  const failed = timelineAsync.status === 'error' && timelineAsync.error !== null
  const isEmpty = succeeded && events.length === 0

  const runEventCount =
    events === null ? null : events.filter((event) => isRunEvent(event)).length
  /**
   * 派生提示（不新增契约字段）：趋势表有的测评、时间线没记上（写入钩子失败返回 None）。
   * 只在时间线读取成功且趋势表已取得时才算，避免加载期闪一条假警告。
   */
  const missingCount =
    succeeded && runRows !== null && runEventCount !== null
      ? Math.max(0, runRows.length - runEventCount)
      : 0

  /** 趋势表也空时，页面已经给了「开始测评」主态；此处只补一行说明，避免两个同样的 CTA 堆叠。 */
  const trendEmpty = runRows !== null && runRows.length === 0

  return (
    <section className="sc-tl">
      <div className="sc-tl-head">
        <h2 className="sc-tl-title">成长时间线</h2>
        {succeeded ? (
          <p className="sc-tl-meta" aria-live="polite">
            {`共 ${events.length} 条 · 按时间倒序 · 记录本版本起的完成事件`}
          </p>
        ) : null}
      </div>

      {missingCount > 0 ? (
        <p className="sc-tl-note">
          {`有 ${missingCount} 次测评未能记入成长记忆，成绩仍在趋势表中`}
        </p>
      ) : null}

      {loading ? (
        <PhaseLoader title="正在读取成长时间线" phases={['读取成长事件', '对齐指标']} active={0} />
      ) : null}

      {failed && timelineAsync.error ? (
        <InlineError
          message={timelineAsync.error.message}
          onRetry={timelineAsync.reload}
          retryLabel="重新读取"
        />
      ) : null}

      {isEmpty ? (
        trendEmpty ? (
          <p className="sc-tl-meta">
            成长记录从本版本上线起写入 —— 完成一次面试或笔试后，这里会出现第一条
          </p>
        ) : (
          <>
            <EmptyState
              reason="还没有成长记录 —— 完成一次面试或笔试，这里就会留下第一条"
              actionLabel="开始测评"
              actionTo="/exam"
            />
            <p className="sc-tl-meta">历史数据从本版本上线起记录</p>
          </>
        )
      ) : null}

      {succeeded && events.length > 0 ? (
        <div
          className="sc-tl-scroll"
          role="region"
          aria-label={`成长时间线，共 ${events.length} 条`}
          tabIndex={0}
        >
          {events.map((event, index) => (
            <TimelineEvent key={event.id} event={event} latest={index === 0} />
          ))}
        </div>
      ) : null}
    </section>
  )
}
