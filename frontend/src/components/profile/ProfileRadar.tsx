import { useState } from 'react'

import type { Report, RunSummary } from '../../api/types'
import {
  CAPABILITY_BASELINE,
  capabilityAxes,
  capabilityCoverage,
  radarPath,
  radarPoints,
  radarPolygon,
} from '../../lib/profileRadar'
import { Card } from '../ui/Card'

/** 画布尺寸写成常量（与 RingProgress 的 size/stroke 同一做法），CSS 只负责布局，不出现裸尺寸。 */
const SIZE = 220
const CENTER = SIZE / 2
const RADIUS = 76
/** 轴序号离圆心的距离（比半径多留 14，落在画布内）。 */
const LABEL_RADIUS = RADIUS + 14
/** 网格环：25% / 50% / 75% / 100%。 */
const RING_LEVELS = [0.25, 0.5, 0.75, 1]
/** 图例小线段的画布尺寸（横线只需要这几个常量）。 */
const SWATCH_WIDTH = 18
const SWATCH_HEIGHT = 8

function anchorOf(x: number): 'start' | 'middle' | 'end' {
  if (Math.abs(x - CENTER) < 6) return 'middle'
  return x > CENTER ? 'start' : 'end'
}

type SeriesKey = 'me' | 'average' | 'top'

/** 图例里的小线段：颜色走 CSS 类，虚线间隔作为 SVG 属性（不在 CSS 里写裸尺寸）。 */
function Swatch({ series }: { series: SeriesKey }) {
  const dash = series === 'average' ? '4 3' : series === 'top' ? '2 3' : undefined
  return (
    <svg
      className={`sc-radar-swatch is-${series}`}
      width={SWATCH_WIDTH}
      height={SWATCH_HEIGHT}
      viewBox={`0 0 ${SWATCH_WIDTH} ${SWATCH_HEIGHT}`}
      aria-hidden="true"
    >
      <line
        x1={0}
        y1={SWATCH_HEIGHT / 2}
        x2={SWATCH_WIDTH}
        y2={SWATCH_HEIGHT / 2}
        strokeWidth={2}
        strokeDasharray={dash}
      />
    </svg>
  )
}

export interface ProfileRadarProps {
  /** 最新报告：没有报告时深度 / 广度按「无数据」处理。 */
  report: Report | null
  /** 成绩历史（服务端时间倒序）：技术力取最近一次、学习力看同类相邻对比。 */
  runs: RunSummary[]
}

/**
 * 能力雷达：个人测评 vs 参考均线 / 参考标杆。
 *
 * 七轴读数全部来自已发生的测评证据（见 `lib/profileRadar.ts` 的 `CAPABILITY_BASIS`），
 * 右侧图例给出可核对的原值；两条参考线是产品设定的刻度，**不是真实市场调研数据**，
 * 页面文案与图注都写明，避免被读成「能力评级 / 及格线」。
 *
 * 两条参考线都可勾选显隐（默认都显示）：平均水平画红色阴影、标杆水平画金色阴影，
 * 个人区域用强调色填充，三层叠在一起时个人区域最上层，读数以右侧原值为准。
 */
export function ProfileRadar({ report, runs }: ProfileRadarProps) {
  /** 两条参考线默认都显示；勾选框只控制显示，不影响任何读数与基线常量。 */
  const [showAverage, setShowAverage] = useState(true)
  const [showTop, setShowTop] = useState(true)
  const axes = capabilityAxes({ report, runs })
  const ratios = axes.map((axis) => axis.ratio)
  const areaPath = radarPath(radarPoints(ratios, CENTER, CENTER, RADIUS))
  const labelPoints = radarPoints(axes.map(() => 1), CENTER, CENTER, LABEL_RADIUS)
  const averagePoints = radarPoints(
    axes.map(() => CAPABILITY_BASELINE.average),
    CENTER,
    CENTER,
    RADIUS,
  )
  const topPoints = radarPoints(axes.map(() => CAPABILITY_BASELINE.top), CENTER, CENTER, RADIUS)
  const filledCount = capabilityCoverage(axes)

  const percentOf = (value: number): string => `${Math.round(value * 100)}%`

  /** 只描述当前实际画出来的参考线，避免勾掉后读屏仍报「参考均线」。 */
  const baselineText = [
    showAverage ? `平均水平 ${percentOf(CAPABILITY_BASELINE.average)}` : '',
    showTop ? `标杆水平 ${percentOf(CAPABILITY_BASELINE.top)}` : '',
  ]
    .filter(Boolean)
    .join('、')

  const ariaLabel = `能力雷达（按测评证据，不代表能力评级）：${axes
    .map((axis) => `${axis.title} ${axis.reading}`)
    .join('、')}${baselineText === '' ? '；未显示参考线' : `；${baselineText}`}`

  return (
    <Card className="sc-radar-card">
      <div className="sc-radar-head">
        <h3 className="sc-coach-blocktitle">能力雷达</h3>
        <p className="sc-coach-meta">
          {filledCount === 0 ? '还没有测评数据' : `${filledCount}/${axes.length} 个维度有测评证据`}
        </p>
      </div>

      {filledCount === 0 ? (
        <p className="sc-coach-note">
          还没有可用的测评数据。先完成一次召对或科考，雷达就会按真实得分生成；
          这里不预填、也不估算任何能力值。
        </p>
      ) : (
        <>
          <div className="sc-radar-wrap">
            <svg
              className="sc-radar-svg"
              width={SIZE}
              height={SIZE}
              viewBox={`0 0 ${SIZE} ${SIZE}`}
              role="img"
              aria-label={ariaLabel}
            >
              {RING_LEVELS.map((level) => (
                <polygon
                  key={`ring-${level}`}
                  className="sc-radar-ring"
                  points={radarPolygon(radarPoints(axes.map(() => level), CENTER, CENTER, RADIUS))}
                />
              ))}

              {labelPoints.map((point, index) => (
                <line
                  key={`axis-${axes[index].key}`}
                  className="sc-radar-axis"
                  x1={CENTER}
                  y1={CENTER}
                  x2={point.x}
                  y2={point.y}
                />
              ))}

              {/* 参考线先画（阴影在个人区域之下），勾选框关掉就整层不渲染。 */}
              {showTop ? (
                <polygon
                  className="sc-radar-series is-top"
                  points={radarPolygon(topPoints)}
                  strokeWidth={1.5}
                  strokeDasharray="2 3"
                />
              ) : null}
              {showAverage ? (
                <polygon
                  className="sc-radar-series is-average"
                  points={radarPolygon(averagePoints)}
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                />
              ) : null}

              {areaPath === '' ? null : (
                <path className="sc-radar-area" d={areaPath} strokeWidth={2} />
              )}

              {radarPoints(ratios, CENTER, CENTER, RADIUS).map((point, index) => (
                <circle
                  key={`dot-${axes[index].key}`}
                  className="sc-radar-dot"
                  cx={point.x}
                  cy={point.y}
                  r={3}
                />
              ))}

              {labelPoints.map((point, index) => (
                <text
                  key={`label-${axes[index].key}`}
                  className="sc-radar-label"
                  x={point.x}
                  y={point.y}
                  textAnchor={anchorOf(point.x)}
                  dominantBaseline="central"
                >
                  {index + 1}
                </text>
              ))}
            </svg>

            <div className="sc-radar-legend">
              <ul className="sc-radar-series-list" aria-label="系列图例与显隐开关">
                <li className="sc-radar-series-item">
                  <Swatch series="me" />
                  <span>我的测评（围合区域已填充）</span>
                </li>
                <li className="sc-radar-series-item">
                  <label className="sc-radar-toggle">
                    <input
                      type="checkbox"
                      checked={showAverage}
                      onChange={(event) => setShowAverage(event.target.checked)}
                    />
                    <Swatch series="average" />
                    <span>平均水平 {percentOf(CAPABILITY_BASELINE.average)}（红色阴影）</span>
                  </label>
                </li>
                <li className="sc-radar-series-item">
                  <label className="sc-radar-toggle">
                    <input
                      type="checkbox"
                      checked={showTop}
                      onChange={(event) => setShowTop(event.target.checked)}
                    />
                    <Swatch series="top" />
                    <span>标杆水平 {percentOf(CAPABILITY_BASELINE.top)}（金色阴影）</span>
                  </label>
                </li>
              </ul>

              <ol className="sc-radar-rows" aria-label="能力维度读数">
                {axes.map((axis, index) => (
                  <li className="sc-radar-row" key={axis.key}>
                    <span className="sc-radar-num sc-mono">{index + 1}</span>
                    <span className="sc-radar-axis-info">
                      <span className="sc-radar-title">{axis.title}</span>
                      <span className="sc-radar-basis">{axis.basis}</span>
                    </span>
                    <span
                      className={
                        axis.filled ? 'sc-radar-reading sc-mono' : 'sc-radar-reading sc-mono is-empty'
                      }
                    >
                      {axis.reading}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          </div>

          <p className="sc-coach-note">
            平均水平（红色阴影）/ 标杆水平（金色阴影）是产品设定的比对刻度，不是真实市场统计数据，
            勾选框只控制这两层阴影的显隐；雷达画的是测评证据（得分率、趋势、难度、方向覆盖），
            不代表能力评级，也不代表熟练度。
          </p>
        </>
      )}
    </Card>
  )
}
