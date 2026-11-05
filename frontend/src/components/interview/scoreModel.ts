import type { RingState } from '../ui/RingProgress'

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
