import { api } from '../../api/client'
import { RingProgress } from './RingProgress'
import { useAsync } from '../../lib/useAsync'
import { computeStreak, type StreakView } from '../../lib/streak'

/**
 * 顶栏 streak 徽章（r84 §3）：「连续 N 天 · 本周 x/7」+ 一枚迷你周进度环。
 *
 * - 数据源是历史列表（本机时区按天去重），**纯前端统计**，不动后端；
 * - 拉取失败/还没登出问题一律**静默隐藏**：这是锦上添花的信息，不值得为它报错；
 * - 完全没记录时也不渲染（新用户顶栏不该多一个 0/7 的挫败感）。
 */
export function StreakBadge() {
  // history() 不收 AbortSignal（分页接口固定形状）：取消时 useAsync 的 active 标记会丢弃结果。
  const state = useAsync(() => api.history({ limit: 200, page: 1 }), [])

  if (state.status !== 'success' || state.data === null) return null
  const view: StreakView = computeStreak(state.data.items)
  if (view.weekDone === 0 && view.streakDays === 0) return null

  return (
    <span className="sc-streak" data-testid="streak-badge" aria-label={`连续学习 ${view.streakDays} 天，本周 ${view.weekDone} 天，目标 7 天`}>
      <RingProgress
        size={22}
        stroke={3}
        value={view.weekDone}
        max={view.weekTarget}
        ariaLabel={undefined}
      />
      <span>
        连续 <span className="sc-streak-count">{view.streakDays}</span> 天 · 本周{' '}
        <span className="sc-streak-count">
          {view.weekDone}/{view.weekTarget}
        </span>
      </span>
    </span>
  )
}
