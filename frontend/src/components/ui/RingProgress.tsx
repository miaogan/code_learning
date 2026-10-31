export type RingState = 'default' | 'warn' | 'danger' | 'success' | 'indeterminate'

export interface RingProgressProps {
  /** 计时环 64 / 得分环 56 / 上传环 56（DESIGN §0.7 第 1–2 条） */
  size?: 56 | 64
  stroke?: number
  value?: number
  max?: number
  label?: string
  state?: RingState
  ariaLabel?: string
}

/** 环形进度：轨道 + 圆头弧，起点 −90°；indeterminate 用于「评分中 / 解析中」。 */
export function RingProgress({
  size = 64,
  stroke = 6,
  value = 0,
  max = 100,
  label,
  state = 'default',
  ariaLabel,
}: RingProgressProps) {
  const radius = size / 2 - stroke
  const circumference = 2 * Math.PI * radius
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0
  const isIndeterminate = state === 'indeterminate'
  const dash = isIndeterminate ? circumference * 0.25 : circumference * ratio
  const offset = isIndeterminate ? 0 : circumference * (1 - ratio)
  const classes = ['sc-ring', `sc-ring--${size}`, `is-${state}`]

  return (
    <svg
      className={classes.join(' ')}
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role={ariaLabel ? 'img' : undefined}
      aria-label={ariaLabel}
      aria-hidden={ariaLabel ? undefined : true}
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={stroke}
        className="sc-ring-track"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={stroke}
        className="sc-ring-value"
        strokeDasharray={`${dash} ${circumference - dash}`}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      {label ? (
        <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" className="sc-ring-text">
          {label}
        </text>
      ) : null}
    </svg>
  )
}
