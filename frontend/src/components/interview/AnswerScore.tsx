import { useEffect, useState } from 'react'
import { formatScore } from '../../lib/format'
import { scoreTier, type ScoreTier } from './chatModel'

/** 出分计数时长（与 ScoreBadge 同一口径：DESIGN §0.4 得分数字 0 → 目标 600ms）。 */
const REVEAL_MS = 600

/** 档位词：颜色只是辅助，档位词与数字同时出现（色盲可读，DESIGN §5）。 */
const TIER_LABEL: Record<ScoreTier, string> = {
  good: '良好',
  mid: '一般',
  low: '薄弱',
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** 得分数字 0 → 目标计数；减少动效时直接给终值。 */
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

export interface AnswerScoreProps {
  /** 0–10，服务端四舍五入到 1 位 */
  score: number
  /** 服务端点评原文：**逐字渲染**，不 trim、不截断、不加省略号（AC-5） */
  comment: string
}

/**
 * 候选人气泡内的评分区（最小高 `--iq-strip-min-h`）：
 * 行一「本题得分」+ 得分徽章（等宽 tabular-nums）+ 档位词；行二点评逐字展开。
 */
export function AnswerScore({ score, comment }: AnswerScoreProps) {
  const safe = Number.isFinite(score) ? Math.min(10, Math.max(0, score)) : 0
  const shown = useRevealedScore(safe)
  const final = formatScore(safe)
  const tier = scoreTier(score)
  const tierLabel = TIER_LABEL[tier]
  const ariaText = `本题得分 ${final} 分，满分 10 分，评价${tierLabel}`

  return (
    <div className="sc-iq-strip">
      <div className="sc-iq-strip-row">
        <span className="sc-iq-score-label">本题得分</span>
        {/*
          role="img" + aria-label：视觉数字在 600ms 内递增，若暴露为文本会让屏幕阅读器逐帧播报；
          以整句 aria-label 提供等价信息（含档位词），读一次即完整。
        */}
        <span className={`sc-iq-score sc-iq-score--${tier}`} role="img" aria-label={ariaText}>
          {formatScore(shown)} / 10
        </span>
        <span className="sc-iq-tier">{tierLabel}</span>
      </div>
      {/* 点评逐字：white-space: pre-wrap 由样式承接换行，此处不做任何字符串加工 */}
      <p className="sc-iq-comment">{comment}</p>
    </div>
  )
}
