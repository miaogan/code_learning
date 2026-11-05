import type { TutorialLevel } from '../../lib/tutorialTypes'

/** 难度档位 → 样式修饰类：绿 / 中性 / 黄三档色序，与方向标签（accent 蓝）区分开。 */
const LEVEL_CLASS: Record<TutorialLevel, string> = {
  基础: 'sc-chip--level-basic',
  进阶: 'sc-chip--level-mid',
  高级: 'sc-chip--level-high',
}

export interface LevelChipProps {
  level: TutorialLevel
}

/** 难度标签：目录卡片与文章页共用，保证「基础 / 进阶 / 高级」在两处看起来是同一个东西。 */
export function LevelChip({ level }: LevelChipProps) {
  return <span className={`sc-chip ${LEVEL_CLASS[level]}`}>{level}</span>
}
