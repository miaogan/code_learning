import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../../api/client'
import { RingProgress } from './RingProgress'
import { useAsync } from '../../lib/useAsync'
import { onActivityChanged } from '../../lib/activityEvents'
import { computeStreakFromDays, type StreakView } from '../../lib/streak'

/**
 * 顶栏 streak 徽章（r84 §3 / r138 口径修正）：「连续 N 天 · 本周 x/7」+ 迷你周进度环。
 *
 * - 数据源是 `/api/activity/days`（测评完成 + 演武作答 + 学堂阅读，服务端按本机时区
 *   折算去重），纯展示，不动业务数据；
 * - 写侧完成后发 `activity-changed` 事件，切页与窗口重新聚焦也重取——不再整页刷新才更新；
 * - 拉取失败/还没登出问题一律**静默隐藏**：这是锦上添花的信息；完全没记录也不渲染，
 *   新用户顶栏不该多一个 0/7 的挫败感。
 */
export function StreakBadge() {
  const { pathname } = useLocation()
  const state = useAsync(() => api.activityDays(), [pathname])

  useEffect(() => onActivityChanged(state.reload), [state.reload])

  if (state.status !== 'success' || state.data === null) return null
  const view: StreakView = computeStreakFromDays(state.data.days)
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
