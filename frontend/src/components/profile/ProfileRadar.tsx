import type { Profile } from '../../api/types'
import { radarAxes, radarCoverage, radarPath, radarPoints } from '../../lib/profileRadar'
import { Card } from '../ui/Card'

/** 画布尺寸写成常量（与 RingProgress 的 size/stroke 同一做法），CSS 只负责布局，不出现裸尺寸。 */
const SIZE = 220
const CENTER = SIZE / 2
const RADIUS = 76
/** 轴序号离圆心的距离（比半径多留 14，落在画布内）。 */
const LABEL_RADIUS = RADIUS + 14
/** 网格环：25% / 50% / 75% / 100%。 */
const RING_LEVELS = [0.25, 0.5, 0.75, 1]

function anchorOf(x: number): 'start' | 'middle' | 'end' {
  if (Math.abs(x - CENTER) < 6) return 'middle'
  return x > CENTER ? 'start' : 'end'
}

export interface ProfileRadarProps {
  profile: Profile
}

/**
 * 画像五维雷达（信息填充度 / 证据覆盖）。
 *
 * **不表达能力水平**：轴值 = 该维度内容量按 `RADAR_REFERENCE` 归一（见 `lib/profileRadar.ts`），
 * 右侧图例同时给出真实计数，任何读数都可人工核对；文案与页面副标题重复声明「不代表能力」，
 * 避免被当成能力评分或熟练度（产品的 anti-goal）。
 */
export function ProfileRadar({ profile }: ProfileRadarProps) {
  const axes = radarAxes(profile)
  const ratios = axes.map((axis) => axis.ratio)
  const area = radarPoints(ratios, CENTER, CENTER, RADIUS)
  const areaPath = radarPath(area)
  const labelPoints = radarPoints(axes.map(() => 1), CENTER, CENTER, LABEL_RADIUS)
  const filledCount = radarCoverage(axes)

  const ariaLabel = `画像填充度雷达（不代表能力水平）：${axes
    .map((axis) => `${axis.title} ${axis.reading}`)
    .join('、')}`

  return (
    <Card className="sc-radar-card">
      <div className="sc-radar-head">
        <h3 className="sc-coach-blocktitle">画像证据覆盖</h3>
        <p className="sc-coach-meta">{`${filledCount}/5 个维度已有内容 · 历史条目不计`}</p>
      </div>

      <div className="sc-radar-wrap">
        <svg
          className="sc-radar-svg"
          width={SIZE}
          height={SIZE}
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          role="img"
          aria-label={ariaLabel}
        >
          {RING_LEVELS.map((level) => {
            const ring = radarPoints(axes.map(() => level), CENTER, CENTER, RADIUS)
            return (
              <polygon
                key={`ring-${level}`}
                className="sc-radar-ring"
                points={ring.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')}
              />
            )
          })}

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

          {areaPath === '' ? null : <path className="sc-radar-area" d={areaPath} />}

          {area.map((point, index) => (
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

        <ol className="sc-radar-legend" aria-label="雷达图图例">
          {axes.map((axis, index) => (
            <li className="sc-radar-row" key={axis.key}>
              <span className="sc-radar-num sc-mono">{index + 1}</span>
              <span className="sc-radar-title">{axis.title}</span>
              <span className={axis.filled ? 'sc-radar-reading sc-mono' : 'sc-radar-reading sc-mono is-empty'}>
                {axis.reading}
              </span>
            </li>
          ))}
        </ol>
      </div>

      <p className="sc-coach-note">
        雷达只表示简历里写了多少、覆盖到哪几个维度（参考上限仅用于画图，不是及格线）；
        它不是能力评分，也不代表熟练度。想要能力证据请去做测评。
      </p>
    </Card>
  )
}
