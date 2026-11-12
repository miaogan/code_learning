import type { RunSummary } from '../../api/types'
import { heatCalendar } from '../../lib/heatCalendar'

export interface HeatCalendarProps {
  rows: readonly RunSummary[]
  /** 仅测试注入；真实调用用默认今天。 */
  today?: Date
}

const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日'] as const

/**
 * 打卡热力图（r84 §2）：近 12 周、周一为首行、最右列止于今天。
 * 色阶映射在 lib/heatCalendar.heatLevel，DOM 只负责按 level 上色（颜色不单独承载
 * 信息——每格带 title 读数，色弱用户悬停/读屏可拿原文）。
 */
export function HeatCalendar({ rows, today }: HeatCalendarProps) {
  const view = heatCalendar(rows, today)
  if (view.total === 0) return null

  return (
    <div className="sc-heat" data-testid="heat-calendar">
      <div className="sc-heat-grid" role="img" aria-label={`近 ${view.weeks} 周打卡热力图：完成 ${view.total} 次，活跃 ${view.activeDays} 天`}>
        {view.cells.map((cell) => (
          <span
            className="sc-heat-cell"
            data-level={cell.level}
            key={cell.key}
            title={`${cell.day}${cell.isFuture ? '' : ` · ${cell.count} 次`}`}
          />
        ))}
      </div>
      <div className="sc-heat-side">
        <p className="sc-heat-summary">
          近 {view.weeks} 周
          {' '}
          <span className="sc-heat-strong">{view.total}</span>
          {' '}次 · 活跃{' '}
          <span className="sc-heat-strong">{view.activeDays}</span>
          {' '}天
        </p>
        <div className="sc-heat-legend" aria-hidden="true">
          <span>少</span>
          {[0, 1, 2, 3, 4].map((level) => (
            <span className="sc-heat-cell" data-level={level} key={level} />
          ))}
          <span>多</span>
        </div>
        <div className="sc-heat-legend" aria-hidden="true">
          {WEEKDAY_LABELS.map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
