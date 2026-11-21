import type { SpokenChapter } from '../../lib/spokenTypes'
import { BE_DISTRIBUTED_CONSISTENCY_SCRIPT } from './be-distributed-consistency'
import { MW_CACHE_STRATEGY_SCRIPT } from './mw-cache-strategy'
import { MW_OBSERVABILITY_SCRIPT } from './mw-observability'

/**
 * M1 试点三章（VERSION-PLAN §4.1）：A 类最抽象 / B 类纯场景 / A+B 混合，
 * 三种最难形态各一个试金石。它们的稿子就是「什么算好的口播稿」的对照标准，
 * 改稿先过 `lib/spoken.ts` 的质量闸，再进人工试听评审。
 */
export const SPOKEN_SCRIPTS: SpokenChapter[] = [
  BE_DISTRIBUTED_CONSISTENCY_SCRIPT,
  MW_CACHE_STRATEGY_SCRIPT,
  MW_OBSERVABILITY_SCRIPT,
]

/** 按教程章 id 取口播稿：听入口只认这一处查找，找不到就说明章节还没做音频。 */
export function spokenChapterById(chapterId: string): SpokenChapter | undefined {
  return SPOKEN_SCRIPTS.find((script) => script.chapterId === chapterId)
}
