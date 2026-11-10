import type { RunSummary } from '../../api/types'
import {
  TREND_META,
  TREND_TARGET,
  buildSeries,
  chartGeometry,
  scoreText,
  targetStatus,
} from '../../lib/trendChart'
import type { TrendSeries } from '../../lib/trendChart'
import { Card } from '../ui/Card'

/** 与 `chartGeometry` 默认值一致：画布尺寸是常量，CSS 只负责缩放与布局。 */
const CHART_WIDTH = 480
const CHART_HEIGHT = 180

function deltaText(series: TrendSeries): string {
  if (series.delta === null) return '只有 1 次记录，暂无法对比'
  if (series.delta === 0) return '与上次同类持平'
  const arrow = series.delta > 0 ? '↑ +' : '↓ −'
  return `较上次同类 ${arrow}${scoreText(Math.abs(series.delta))}`
}

function SeriesChart({ series }: { series: TrendSeries }) {
  const geometry = chartGeometry(series, CHART_WIDTH, CHART_HEIGHT)
  const { dots, path, yTicks, padX, width, height, target, targetY } = geometry
  const first = dots[0]
  const last = dots[dots.length - 1]
  const latestText = series.latest === null ? '—' : `${scoreText(series.latest)} ${series.unit}`
  const targetText = `${scoreText(target)}${series.unit}`
  const status = targetStatus(series)

  const ariaLabel = `${series.title}：共 ${dots.length} 次，最高 ${series.max}${series.unit}；最新 ${latestText}；目标线 ${targetText}`

  return (
    <figure className="sc-chart">
      <figcaption className="sc-chart-caption">
        <span className="sc-chart-title">{series.title}</span>
        <span className="sc-chart-latest sc-mono">{latestText}</span>
      </figcaption>

      <svg
        className="sc-chart-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
      >
        {yTicks.map((tick) => (
          <g key={`tick-${tick.label}`}>
            <line
              className="sc-chart-guide"
              x1={padX}
              y1={tick.y}
              x2={width - padX}
              y2={tick.y}
              strokeWidth={1}
            />
            <text className="sc-chart-tick" x={padX - 6} y={tick.y} textAnchor="end" dominantBaseline="central">
              {tick.label}
            </text>
          </g>
        ))}

        <line
          className="sc-chart-target"
          x1={padX}
          y1={targetY}
          x2={width - padX}
          y2={targetY}
          strokeWidth={1}
        />
        <text className="sc-chart-target-label" x={width - padX} y={targetY - 5} textAnchor="end">
          {`目标 ${targetText}`}
        </text>

        {path === '' ? null : <path className="sc-chart-line" d={path} strokeWidth={2} />}

        {dots.map((dot) => (
          <circle key={dot.id} className="sc-chart-dot" cx={dot.x} cy={dot.y} r={3.5}>
            <title>{`${dot.label} · ${scoreText(dot.score)} ${series.unit}`}</title>
          </circle>
        ))}

        <text className="sc-chart-tick" x={first.x} y={height - 6} textAnchor="start">
          {first.label}
        </text>
        {dots.length > 1 ? (
          <text className="sc-chart-tick" x={last.x} y={height - 6} textAnchor="end">
            {last.label}
          </text>
        ) : null}
      </svg>

      <p className="sc-chart-note">
        {`${deltaText(series)} · 共 ${dots.length} 次（按时间从旧到新） · ${status.text}`}
      </p>
    </figure>
  )
}

export interface TrendChartProps {
  /** 页面已按类型筛选过的行（服务端时间倒序）。这里只按 kind 拆成两条独立序列。 */
  rows: RunSummary[]
}

/**
 * 成绩走势折线图：面试（/10）与笔试（/100）**各画一张**，不共轴（量纲不同）。
 * `score === null` 的行不落点（不补 0），所以「次数」可能少于表格行数，需在图注里说清。
 */
export function TrendChart({ rows }: TrendChartProps) {
  const series = (['interview', 'exam'] as const)
    .map((kind) => buildSeries(rows, kind))
    .filter((item) => item.points.length > 0)

  if (series.length === 0) return null

  return (
    <Card className="sc-chart-card">
      <div className="sc-chart-head">
        <h3 className="sc-coach-blocktitle">成绩走势</h3>
        <p className="sc-coach-meta">
          按时间从旧到新；面试 {TREND_META.interview.max}
          {TREND_META.interview.unit} 与笔试 {TREND_META.exam.max}
          {TREND_META.exam.unit} 量纲不同，分开画、不共轴。未计分的记录不落点。虚线是产品设定的目标线（面试{' '}
          {TREND_TARGET.interview}
          {TREND_META.interview.unit}、笔试 {TREND_TARGET.exam}
          {TREND_META.exam.unit}），只作自我比对，不代表市场统计或招聘分数线。
        </p>
      </div>

      <div className="sc-chart-grid">
        {series.map((item) => (
          <SeriesChart key={item.kind} series={item} />
        ))}
      </div>
    </Card>
  )
}
