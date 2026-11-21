import { describe, expect, it } from 'vitest'
import { SPOKEN_SCRIPTS } from '../content/spoken'
import {
  SPOKEN_SFT_SYSTEM_PROMPT,
  SPOKEN_SFT_VERSION,
  buildSpokenSftSamples,
  sectionOutline,
  spokenSftStats,
} from '../lib/spokenSft'
import type { SpokenForm } from '../lib/spokenTypes'
import { ALL_TUTORIAL_CHAPTERS, chapterById } from '../lib/tutorials'

const SAMPLES = buildSpokenSftSamples(SPOKEN_SCRIPTS, ALL_TUTORIAL_CHAPTERS)

describe('SFT 样本构造', () => {
  it('3 章 × 4 节 = 12 条，且每条都带章/节标识', () => {
    expect(SAMPLES).toHaveLength(12)
    expect(new Set(SAMPLES.map((sample) => sample.chapterId)).size).toBe(3)
    const keys = SAMPLES.map((sample) => `${sample.chapterId}/${sample.sectionId}`)
    expect(new Set(keys).size).toBe(12)
  })

  it('每条是 system → user → assistant 三段，system 带版本号与硬性规则', () => {
    for (const sample of SAMPLES) {
      expect(sample.messages.map((message) => message.role)).toEqual(['system', 'user', 'assistant'])
      expect(sample.messages[0].content).toBe(SPOKEN_SFT_SYSTEM_PROMPT)
    }
    expect(SPOKEN_SFT_SYSTEM_PROMPT).toContain(SPOKEN_SFT_VERSION)
    for (const rule of ['只输出一个 JSON 对象', '不超过 20 字', '不超过 5 句', '2–6 处', '说白了']) {
      expect(SPOKEN_SFT_SYSTEM_PROMPT).toContain(rule)
    }
  })

  it('user 侧带小节标题与原文骨架（骨架来自教程，不是口播稿）', () => {
    for (const sample of SAMPLES) {
      const tutorial = chapterById(sample.chapterId)
      const section = tutorial?.sections.find((item) => item.id === sample.sectionId)
      expect(section, `${sample.chapterId}/${sample.sectionId} 找不到教程小节`).toBeDefined()
      const user = sample.messages[1].content
      expect(user).toContain(section!.title)
      const firstOutline = sectionOutline(section!)[0]
      expect(user).toContain(firstOutline.slice(0, 12))
    }
  })

  it('assistant 目标是合法 JSON，形态与金标稿一致，字段全部落在闭集里', () => {
    for (const sample of SAMPLES) {
      const script = SPOKEN_SCRIPTS.find((item) => item.chapterId === sample.chapterId)
      const goldSection = script?.sections.find((item) => item.sectionId === sample.sectionId)
      const target = JSON.parse(sample.messages[2].content) as {
        form: SpokenForm
        segments: { speaker: string; emotion: string; lines: string[] }[]
      }
      const expected: SpokenForm = goldSection?.form ?? script!.form
      expect(target.form).toBe(expected)
      expect(target.segments.length).toBeGreaterThan(0)
      for (const segment of target.segments) {
        expect(['dou', 'peng', 'narrator']).toContain(segment.speaker)
        expect(['banter', 'setup', 'deadpan', 'punch', 'realize', 'contrast', 'wrap']).toContain(segment.emotion)
        expect(segment.lines.length).toBeGreaterThan(0)
        expect(segment.lines.every((line) => line.trim().length > 0)).toBe(true)
      }
      if (target.form === 'solo') {
        expect(target.segments.every((segment) => segment.speaker === 'narrator')).toBe(true)
      } else {
        const speakers = new Set(target.segments.map((segment) => segment.speaker))
        expect(speakers.has('dou') && speakers.has('peng')).toBe(true)
      }
    }
  })

  it('统计量与 max_length 的余量：每条粗估 800–1900 token', () => {
    const stats = spokenSftStats(SAMPLES)
    expect(stats.samples).toBe(12)
    expect(stats.chapters).toBe(3)
    expect(stats.targetChars).toBeGreaterThan(0)
    const perSample = stats.estimateTokens / stats.samples
    expect(perSample).toBeGreaterThan(800)
    expect(perSample).toBeLessThan(1900)
  })

  it('原文骨架会压平表格与问答，不让训练输入变成空行', () => {
    const cache = ALL_TUTORIAL_CHAPTERS.find((chapter) => chapter.id === 'mw-cache-strategy')
    const section = cache?.sections.find((item) => item.id === 'expire')
    const outline = sectionOutline(section!)
    expect(outline.length).toBeGreaterThan(2)
    expect(outline.join('\n')).toContain('|')
    expect(outline.every((line) => line.trim().length > 0)).toBe(true)
  })
})
