import { useEffect, useState } from 'react'
import { RingProgress } from '../ui/RingProgress'
import type { RingState } from '../ui/RingProgress'
import { formatScore } from '../../lib/format'

/** 出分揭示时长（DESIGN §0.6：得分环 0 → 目标 600ms ease-out）。 */
const REVEAL_MS = 600

/**
 * 得分档位：>7 绿 / 4–7 黄 / <4 红（DESIGN §2.3）。
 * 颜色与数字双通道：环色只是辅助，环内始终有数字，progress strip 复用同一档位。
 */
export function scoreRingState(score: number): RingState {
  if (!Number.isFinite(score)) return 'default'
  if (score > 7) return 'success'
  if (score >= 4) return 'warn'
  return 'danger'
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** 环内数字与弧同步计数：减少动效时直接给终值（DESIGN §0.6「减少动效」）。 */
function useRevealedScore(target: number): number {
  const [shown, setShown] = useState(() => (prefersReducedMotion() ? target : 0))

  useEffect(() => {
    if (prefersReducedMotion() || !Number.isFinite(target)) {
      setShown(target)
      return
    }
    let frame = 0
    const started = performance.now()
    const step = (now: number) => {
      const progress = Math.min(1, (now - started) / REVEAL_MS)
      const eased = 1 - Math.pow(1 - progress, 3)
      setShown(target * eased)
      if (progress < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target])

  return shown
}

export interface ScoreBadgeProps {
  /** 0–10，后端四舍五入到 1 位小数 */
  score: number
  comment: string
}

/**
 * 判分结果唯一展示位：56 得分环 + 0–10 分 + 一句点评（同卡出分，不换页）。
 * 环内文本 ≤3 字符（DESIGN §0.7 第 2 条几何推导）。
 */
export function ScoreBadge({ score, comment }: ScoreBadgeProps) {
  const safe = Number.isFinite(score) ? Math.min(10, Math.max(0, score)) : 0
  const shown = useRevealedScore(safe)
  const final = formatScore(safe)

  return (
    <div className="sc-score-side">
      <RingProgress
        size={56}
        stroke={5}
        value={shown}
        max={10}
        label={formatScore(shown)}
        state={scoreRingState(safe)}
        ariaLabel={`本题得分 ${final} 分，满分 10 分`}
      />
      <p className="sc-mono" aria-live="polite">
        本题 {final} / 10
      </p>
      <p className="sc-score-comment">{comment}</p>
    </div>
  )
}
