/**
 * 章节可听性分层的纯函数层（r150 / M1）。
 *
 * 分层数据在 `content/spoken/coverage.ts`，这里只做「怎么用」：
 * 哪些章进听入口、哪些章进起草流水线、形态默认值是什么。
 * 判据见 VERSION-PLAN §3.1（能否脱离视觉独立成立），不是代码占比。
 */
import type { SpokenForm } from './spokenTypes'
import type { TutorialChapter } from './tutorialTypes'

/** 四层闭集：A 复杂概念 / B 常见场景 / C 必须看 / C′（代码里写 C2）算法演示。 */
export type SpokenLayer = 'A' | 'B' | 'C' | 'C2'

export const SPOKEN_LAYERS: readonly SpokenLayer[] = ['A', 'B', 'C', 'C2']

/** 只有 A / B 做音频；C 与 C2 走「读 + 做」。 */
export const LISTENABLE_LAYERS: readonly SpokenLayer[] = ['A', 'B']

export interface SpokenCoverageEntry {
  chapterId: string
  layer: SpokenLayer
  reason: string
  form?: SpokenForm
}

export function isListenable(layer: SpokenLayer): boolean {
  return LISTENABLE_LAYERS.includes(layer)
}

/** A 是概念章 → 单口；B 是场景章 → 对口；条目上显式给的 form 优先（混合章）。 */
export function spokenFormFor(entry: Pick<SpokenCoverageEntry, 'layer' | 'form'> | undefined): SpokenForm {
  if (!entry) return 'solo'
  return entry.form ?? (entry.layer === 'A' ? 'solo' : 'duo')
}

export function coverageOf(
  entries: readonly SpokenCoverageEntry[],
  chapterId: string,
): SpokenCoverageEntry | undefined {
  return entries.find((entry) => entry.chapterId === chapterId)
}

/** 可听章节 id（保持 coverage 表里的顺序，起草顺序稳定、可复算）。 */
export function listenableChapterIds(entries: readonly SpokenCoverageEntry[]): string[] {
  return entries.filter((entry) => isListenable(entry.layer)).map((entry) => entry.chapterId)
}

/** 可听章节对象：按**教程顺序**返回（与站点目录一致，起草与听入口的顺序可预期）。 */
export function listenableChapters(
  entries: readonly SpokenCoverageEntry[],
  tutorials: readonly TutorialChapter[],
): TutorialChapter[] {
  return tutorials.filter((chapter) => {
    const entry = coverageOf(entries, chapter.id)
    return Boolean(entry && isListenable(entry.layer))
  })
}

export interface CoverageStats {
  chapters: number
  byLayer: Record<SpokenLayer, number>
  listenable: number
  listenableSections: number
}

export function coverageStats(
  entries: readonly SpokenCoverageEntry[],
  tutorials: readonly TutorialChapter[],
): CoverageStats {
  const byLayer: Record<SpokenLayer, number> = { A: 0, B: 0, C: 0, C2: 0 }
  for (const entry of entries) byLayer[entry.layer] += 1
  const listenable = listenableChapters(entries, tutorials)
  return {
    chapters: entries.length,
    byLayer,
    listenable: listenable.length,
    listenableSections: listenable.reduce((sum, chapter) => sum + chapter.sections.length, 0),
  }
}
