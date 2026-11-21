import { describe, expect, it } from 'vitest'
import { SPOKEN_SCRIPTS, spokenChapterById } from '../content/spoken'
import {
  CLAUSE_MAX_CHARS,
  EMOTION_GAIN_MAX,
  EMOTION_SPECS,
  PUNCH_MAX,
  PUNCH_MIN,
  RECAP_MARKER,
  SPOKEN_EMOTIONS,
  estimateSpokenMs,
  flattenSpoken,
  isPengPromoting,
  requiredRecaps,
  sectionForm,
  splitClauses,
  summarizeSpoken,
  validateSpokenChapter,
  validateSpokenLibrary,
} from '../lib/spoken'
import type { SpokenChapter, SpokenSection } from '../lib/spokenTypes'
import type { TutorialChapter } from '../lib/tutorialTypes'
import { ALL_TUTORIAL_CHAPTERS, chapterById } from '../lib/tutorials'

const ONE_SECTION: TutorialChapter = {
  id: 't',
  title: '测试章',
  direction: '后端',
  sub_direction: '通用后端',
  level: '基础',
  summary: '',
  sections: [{ id: 'a', title: 'A 节', blocks: [] }],
}

const TWO_SECTIONS: TutorialChapter = {
  ...ONE_SECTION,
  sections: [
    { id: 'a', title: 'A 节', blocks: [] },
    { id: 'b', title: 'B 节', blocks: [] },
  ],
}

/** 基础稿是「过闸」的：两个 punch + 一个「说白了」，这样每个坏样例只破坏一件事。 */
function baseChapter(section: Partial<SpokenSection> = {}, chapter: Partial<SpokenChapter> = {}): SpokenChapter {
  return {
    chapterId: 't',
    form: 'solo',
    scriptVersion: '0.0.1',
    voice: { model: 'demo-model', emotionGain: 0.5, lead: 'lead' },
    sections: [
      {
        sectionId: 'a',
        title: 'A 节',
        segments: [
          { speaker: 'narrator', emotion: 'banter', lines: [`${RECAP_MARKER}，这是小结。`] },
          { speaker: 'narrator', emotion: 'punch', lines: ['第一个包袱。', '第二个包袱。'] },
        ],
        ...section,
      },
    ],
    ...chapter,
  }
}

function codes(chapter: SpokenChapter, tutorial: TutorialChapter = ONE_SECTION): string[] {
  return validateSpokenChapter(chapter, tutorial).map((issue) => issue.code)
}

const DUO_VOICE = { model: 'demo-model', emotionGain: 0.55, lead: 'lead', support: 'support' }

describe('情绪表', () => {
  it('7 类情绪齐备且中文名互不重复', () => {
    expect(SPOKEN_EMOTIONS).toHaveLength(7)
    expect(new Set(SPOKEN_EMOTIONS).size).toBe(7)
    const labels = SPOKEN_EMOTIONS.map((emotion) => EMOTION_SPECS[emotion].label)
    expect(new Set(labels).size).toBe(7)
  })

  it('停顿非负，且 punch 是「前紧后顿」的那一类', () => {
    for (const emotion of SPOKEN_EMOTIONS) {
      const spec = EMOTION_SPECS[emotion]
      expect(spec.pauseBeforeMs).toBeGreaterThanOrEqual(0)
      expect(spec.pauseAfterMs).toBeGreaterThanOrEqual(0)
      expect(spec.hint.length).toBeGreaterThan(0)
    }
    expect(EMOTION_SPECS.punch.pauseAfterMs).toBeGreaterThan(EMOTION_SPECS.banter.pauseAfterMs)
  })
})

describe('M1 黄金稿三章', () => {
  it('三章都能在教程里找到，且反查一致', () => {
    expect(SPOKEN_SCRIPTS).toHaveLength(3)
    for (const script of SPOKEN_SCRIPTS) {
      const tutorial = chapterById(script.chapterId)
      expect(tutorial, `${script.chapterId} 没有对应教程章`).toBeDefined()
      expect(spokenChapterById(script.chapterId)).toBe(script)
    }
  })

  it('每章的小节与教程逐节对齐（含顺序）', () => {
    for (const script of SPOKEN_SCRIPTS) {
      const tutorial = chapterById(script.chapterId)
      expect(script.sections.map((section) => section.sectionId)).toEqual(
        tutorial?.sections.map((section) => section.id),
      )
    }
  })

  it('三章全部通过质量闸（零 issue）', () => {
    expect(validateSpokenLibrary(SPOKEN_SCRIPTS, ALL_TUTORIAL_CHAPTERS)).toEqual([])
  })

  it('单章 3.5–15 分钟、punch 落在 2–6 次、小结不少于 3 处', () => {
    for (const script of SPOKEN_SCRIPTS) {
      const summary = summarizeSpoken(script)
      expect(summary.minutes).toBeGreaterThanOrEqual(3.5)
      expect(summary.minutes).toBeLessThanOrEqual(15)
      expect(summary.punch).toBeGreaterThanOrEqual(PUNCH_MIN)
      expect(summary.punch).toBeLessThanOrEqual(PUNCH_MAX)
      expect(summary.recaps).toBeGreaterThanOrEqual(3)
      expect(summary.recaps).toBeGreaterThanOrEqual(requiredRecaps(script))
    }
  })

  it('A 类概念章是单口，场景章对口，混合章按小节拆分', () => {
    const distributed = spokenChapterById('be-distributed-consistency')
    const cache = spokenChapterById('mw-cache-strategy')
    const observability = spokenChapterById('mw-observability')
    expect(distributed?.form).toBe('solo')
    expect(flattenSpoken(distributed!).every((utterance) => utterance.speaker === 'narrator')).toBe(true)

    // 混合章：概念小节单口、场景小节对口，章级形态只作缺省值。
    expect(cache?.form).toBe('duo')
    expect(cache?.voice.support).toBeTruthy()
    const cacheForms = cache!.sections.map((section) => sectionForm(cache!, section))
    expect(cacheForms).toContain('solo')
    expect(cacheForms.filter((form) => form === 'duo').length).toBeGreaterThanOrEqual(3)

    // 纯场景章：每个小节都要逗哏与捧哏对得上话。
    expect(observability?.form).toBe('duo')
    expect(observability?.voice.support).toBeTruthy()
    for (const section of observability!.sections) {
      expect(sectionForm(observability!, section)).toBe('duo')
    }
  })
})

describe('质量闸逐条生效', () => {
  it('小句超过 20 字被拦下', () => {
    const long = '这一句故意写得特别长就是用来触发小句上限检查的'
    expect(long.length).toBeGreaterThan(CLAUSE_MAX_CHARS)
    const chapter = baseChapter({
      segments: [
        { speaker: 'narrator', emotion: 'banter', lines: [`${long}。`] },
        { speaker: 'narrator', emotion: 'punch', lines: ['第一个包袱。', '第二个包袱。'] },
      ],
    })
    expect(codes(chapter)).toContain('clause_too_long')
  })

  it('逗哏单次超过 5 句被拦下', () => {
    const chapter = baseChapter(
      {
        segments: [
          { speaker: 'dou', emotion: 'banter', lines: ['一。', '二。', '三。', '四。', '五。', '六。'] },
          { speaker: 'peng', emotion: 'deadpan', lines: ['那数据改了呢？'] },
          { speaker: 'dou', emotion: 'punch', lines: ['第一个包袱。', '第二个包袱。'] },
        ],
      },
      { form: 'duo', voice: DUO_VOICE },
    )
    expect(codes(chapter)).toContain('dou_turn_too_long')
  })

  it('捧哏全是「嗯」被拦下', () => {
    const chapter = baseChapter(
      {
        segments: [
          { speaker: 'dou', emotion: 'banter', lines: ['缓存就是放近点儿。'] },
          { speaker: 'peng', emotion: 'deadpan', lines: ['嗯。', '嗯。', '嗯。'] },
          { speaker: 'peng', emotion: 'deadpan', lines: ['那要是改了呢？'] },
          { speaker: 'dou', emotion: 'punch', lines: ['第一个包袱。', '第二个包袱。'] },
        ],
      },
      { form: 'duo', voice: DUO_VOICE },
    )
    expect(codes(chapter)).toContain('peng_filler_ratio')
  })

  it('对口缺捧哏、缺音色、单口混入逗哏都被拦下', () => {
    const noPeng = baseChapter(
      { segments: [{ speaker: 'dou', emotion: 'banter', lines: ['一个人说完全场。'] }] },
      { form: 'duo', voice: DUO_VOICE },
    )
    expect(codes(noPeng)).toContain('duo_missing_peng')

    const noVoice = baseChapter({}, { form: 'duo', voice: { model: 'm', emotionGain: 0.55, lead: 'lead' } })
    expect(codes(noVoice)).toContain('duo_missing_voice')

    const soloWithDou = baseChapter({
      segments: [{ speaker: 'dou', emotion: 'banter', lines: ['单口里冒出个逗哏。'] }],
    })
    expect(codes(soloWithDou)).toContain('speaker_solo')
  })

  it('punch 过少、缺小结、情绪强度越界都被拦下', () => {
    const noPunch = baseChapter({
      segments: [{ speaker: 'narrator', emotion: 'banter', lines: [`${RECAP_MARKER}，这是小结。`] }],
    })
    expect(codes(noPunch)).toContain('punch_count')

    const noRecap = baseChapter({
      segments: [
        { speaker: 'narrator', emotion: 'banter', lines: ['开场。'] },
        { speaker: 'narrator', emotion: 'punch', lines: ['第一个包袱。', '第二个包袱。'] },
      ],
    })
    expect(codes(noRecap)).toContain('recap_missing')

    const hotGain = baseChapter({}, { voice: { model: 'm', emotionGain: EMOTION_GAIN_MAX + 0.2, lead: 'lead' } })
    expect(codes(hotGain)).toContain('emotion_gain')
  })

  it('小节缺稿、多稿、顺序错乱都被拦下', () => {
    expect(codes(baseChapter({}, { sections: [] }))).toContain('section_missing')

    const extra = baseChapter({}, {
      sections: [
        ...baseChapter().sections,
        { sectionId: 'zzz', title: '多出来的', segments: [{ speaker: 'narrator', emotion: 'banter', lines: ['多余。'] }] },
      ],
    })
    expect(codes(extra)).toContain('section_unknown')

    const reversed: SpokenChapter = {
      ...baseChapter(),
      sections: [baseChapter().sections[0], { ...baseChapter().sections[0], sectionId: 'b', title: 'B 节' }].reverse(),
    }
    expect(codes(reversed, TWO_SECTIONS)).toContain('section_order')
  })

  it('教程里找不到章时给出 unknown_tutorial，而不是静默放过', () => {
    const issues = validateSpokenChapter(baseChapter(), undefined)
    expect(issues.map((issue) => issue.code)).toContain('unknown_tutorial')
  })
})

describe('派生函数', () => {
  it('splitClauses 按中英标点切句并丢掉空段', () => {
    expect(splitClauses('先说缓存，再说 TTL；最后说雪崩。')).toEqual(['先说缓存', '再说 TTL', '最后说雪崩'])
    expect(splitClauses('，。')).toEqual([])
  })

  it('捧哏推进判定：短附和不算，带问题才算', () => {
    expect(isPengPromoting('嗯。')).toBe(false)
    expect(isPengPromoting('哟。')).toBe(false)
    expect(isPengPromoting('真的假的')).toBe(true)
    expect(isPengPromoting('那要是改了呢？')).toBe(true)
  })

  it('小节形态缺省继承章级，显式声明可覆盖', () => {
    const chapter = baseChapter()
    expect(sectionForm(chapter, chapter.sections[0])).toBe('solo')
    const mixed = { ...chapter, form: 'duo' as const }
    expect(sectionForm(mixed, mixed.sections[0])).toBe('duo')
    expect(sectionForm(mixed, { ...mixed.sections[0], form: 'solo' as const })).toBe('solo')
  })

  it('摘要与时长估算来自同一份展平口径', () => {
    const chapter = baseChapter()
    const summary = summarizeSpoken(chapter)
    expect(summary.lines).toBe(flattenSpoken(chapter).length)
    expect(summary.sections).toBe(1)
    expect(summary.punch).toBe(2)
    expect(summary.recaps).toBe(1)
    expect(estimateSpokenMs(chapter)).toBeGreaterThan(0)
    expect(requiredRecaps(chapter)).toBe(1)
    expect(summary.chars).toBeGreaterThan(0)
  })
})
