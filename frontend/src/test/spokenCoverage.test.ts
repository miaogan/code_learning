import { describe, expect, it } from 'vitest'
import { SPOKEN_COVERAGE } from '../content/spoken/coverage'
import {
  LISTENABLE_LAYERS,
  SPOKEN_LAYERS,
  coverageOf,
  coverageStats,
  isListenable,
  listenableChapterIds,
  listenableChapters,
  spokenFormFor,
} from '../lib/spokenCoverage'
import { ALL_TUTORIAL_CHAPTERS } from '../lib/tutorials'

describe('可听性分层', () => {
  it('分层闭集与判定口径', () => {
    expect(SPOKEN_LAYERS).toEqual(['A', 'B', 'C', 'C2'])
    expect(LISTENABLE_LAYERS).toEqual(['A', 'B'])
    expect(isListenable('A')).toBe(true)
    expect(isListenable('B')).toBe(true)
    expect(isListenable('C')).toBe(false)
    expect(isListenable('C2')).toBe(false)
  })

  it('每个教程章都有分层，且没有多余 / 重复的条目', () => {
    const tutorialIds = ALL_TUTORIAL_CHAPTERS.map((chapter) => chapter.id).sort()
    const coverageIds = SPOKEN_COVERAGE.map((entry) => entry.chapterId).sort()
    expect(coverageIds).toEqual(tutorialIds)
    expect(new Set(coverageIds).size).toBe(coverageIds.length)
  })

  it('每条都写了理由（不允许空话占位）', () => {
    for (const entry of SPOKEN_COVERAGE) {
      expect(entry.reason.trim().length).toBeGreaterThan(4)
    }
  })

  it('分布落在规划口径：A 29 / B 16 / C 11 / C′ 4，可听 45 章', () => {
    const stats = coverageStats(SPOKEN_COVERAGE, ALL_TUTORIAL_CHAPTERS)
    expect(stats.chapters).toBe(60)
    expect(stats.byLayer).toEqual({ A: 29, B: 16, C: 11, C2: 4 })
    expect(stats.listenable).toBe(45)
    expect(stats.listenableSections).toBeGreaterThan(150)
  })

  it('三章黄金稿都在可听层，且 C/C′ 章不进可听子集', () => {
    for (const id of ['be-distributed-consistency', 'mw-cache-strategy', 'mw-observability']) {
      expect(isListenable(coverageOf(SPOKEN_COVERAGE, id)!.layer)).toBe(true)
    }
    const listenable = new Set(listenableChapterIds(SPOKEN_COVERAGE))
    for (const entry of SPOKEN_COVERAGE) {
      if (entry.layer === 'C' || entry.layer === 'C2') {
        expect(listenable.has(entry.chapterId)).toBe(false)
      }
    }
  })

  it('形态默认值：A → 单口，B → 对口，条目显式 form 优先', () => {
    expect(spokenFormFor({ layer: 'A' })).toBe('solo')
    expect(spokenFormFor({ layer: 'B' })).toBe('duo')
    expect(spokenFormFor({ layer: 'A', form: 'duo' })).toBe('duo')
    expect(spokenFormFor(undefined)).toBe('solo')
    // 混合章 mw-cache-strategy 在表里显式覆盖为 duo（与黄金稿一致）
    expect(spokenFormFor(coverageOf(SPOKEN_COVERAGE, 'mw-cache-strategy'))).toBe('duo')
  })

  it('可听章节按教程顺序返回，忽略表里多写的 id', () => {
    const chapters = listenableChapters(SPOKEN_COVERAGE, ALL_TUTORIAL_CHAPTERS)
    expect(chapters.map((chapter) => chapter.id)).toEqual(
      ALL_TUTORIAL_CHAPTERS.filter((chapter) => isListenable(coverageOf(SPOKEN_COVERAGE, chapter.id)!.layer)).map(
        (chapter) => chapter.id,
      ),
    )
    const withGhost = listenableChapters(
      [...SPOKEN_COVERAGE, { chapterId: 'ghost-chapter', layer: 'A' as const, reason: '不存在' }],
      ALL_TUTORIAL_CHAPTERS,
    )
    expect(withGhost).toHaveLength(chapters.length)
  })
})
