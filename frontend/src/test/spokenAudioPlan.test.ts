import { describe, expect, it } from 'vitest'
import { SPOKEN_SCRIPTS } from '../content/spoken'
import { EMOTION_SPECS } from '../lib/spoken'
import { audioSrcFor, buildAudioPlan } from '../lib/spokenAudioPlan'

const CACHE = SPOKEN_SCRIPTS.find((chapter) => chapter.chapterId === 'mw-cache-strategy')!

describe('音频计划', () => {
  it('每章按小节产出计划，路径固定为 /audio/<章>/<节>.wav', () => {
    const plan = buildAudioPlan(CACHE)
    expect(plan.chapterId).toBe('mw-cache-strategy')
    expect(plan.sections.map((section) => section.sectionId)).toEqual(
      CACHE.sections.map((section) => section.sectionId),
    )
    for (const section of plan.sections) {
      expect(section.src).toBe(`/audio/mw-cache-strategy/${section.sectionId}.wav`)
      expect(audioSrcFor('mw-cache-strategy', section.sectionId)).toBe(section.src)
    }
  })

  it('合成单元 = 情绪段，停顿取自情绪表（不在驱动里再猜一次）', () => {
    const plan = buildAudioPlan(CACHE)
    for (const section of plan.sections) {
      const gold = CACHE.sections.find((item) => item.sectionId === section.sectionId)!
      expect(section.units).toHaveLength(gold.segments.length)
      section.units.forEach((unit, index) => {
        const segment = gold.segments[index]
        expect(unit.speaker).toBe(segment.speaker)
        expect(unit.emotion).toBe(segment.emotion)
        expect(unit.lines).toEqual(segment.lines)
        expect(unit.pauseBeforeMs).toBe(EMOTION_SPECS[segment.emotion].pauseBeforeMs)
        expect(unit.pauseAfterMs).toBe(EMOTION_SPECS[segment.emotion].pauseAfterMs)
      })
    }
  })

  it('估算时长与章节摘要同量级（同源，不各算一套）', () => {
    const plan = buildAudioPlan(CACHE)
    const estimateMinutes = plan.sections.reduce((sum, section) => sum + section.estimateMs, 0) / 60000
    expect(estimateMinutes).toBeGreaterThan(3)
    expect(estimateMinutes).toBeLessThan(20)
  })

  it('三章都能生成计划，且每节至少一个合成单元', () => {
    for (const chapter of SPOKEN_SCRIPTS) {
      const plan = buildAudioPlan(chapter)
      expect(plan.sections.length).toBeGreaterThan(0)
      for (const section of plan.sections) expect(section.units.length).toBeGreaterThan(0)
    }
  })
})
