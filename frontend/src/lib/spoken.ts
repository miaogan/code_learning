/**
 * 口播稿的纯函数层（r150 / M1）：情绪表、展平、时长估算与**脚本质量闸**。
 *
 * 质检规则直接来自 VERSION-PLAN §5.7 的「硬约束（写进内容校验，不靠人工约定）」：
 * 逗哏单次 ≤5 句、捧哏必须推进、每 3–5 分钟一个「说白了」、punch 2–6 次、小句 ≤20 字。
 * 3 章黄金稿必须零 issue 才算过闸（`spoken.test.ts` 锁死），改脚本先过这里再谈录音。
 */
import type { SpokenChapter, SpokenEmotion, SpokenForm, SpokenSection, SpokenSpeaker } from './spokenTypes'
import type { TutorialChapter } from './tutorialTypes'

/** 情绪规格：暂停与表演提示按情绪单点定义，播放器图例与质检报错共用同一份措辞。 */
export interface EmotionSpec {
  /** 中文名：界面图例用。 */
  label: string
  /** 段前停顿（ms）。 */
  pauseBeforeMs: number
  /** 段后停顿（ms）。 */
  pauseAfterMs: number
  /** 表演提示：制作与人工试听评审时的对照口径，不参与运行期。 */
  hint: string
}

export const EMOTION_SPECS: Record<SpokenEmotion, EmotionSpec> = {
  banter: { label: '闲聊', pauseBeforeMs: 0, pauseAfterMs: 160, hint: '语速偏快、音量偏轻，像真在聊天' },
  setup: { label: '下结论', pauseBeforeMs: 200, pauseAfterMs: 260, hint: '一本正经，越肯定越好笑' },
  deadpan: { label: '拆台', pauseBeforeMs: 350, pauseAfterMs: 400, hint: '短、平、不演' },
  punch: { label: '抖包袱', pauseBeforeMs: 450, pauseAfterMs: 700, hint: '前面收着，最后一个字咬住' },
  realize: { label: '恍然', pauseBeforeMs: 500, pauseAfterMs: 600, hint: '短促、上扬后骤停' },
  contrast: { label: '转折', pauseBeforeMs: 420, pauseAfterMs: 200, hint: '前半轻、后半压下来' },
  wrap: { label: '收束', pauseBeforeMs: 400, pauseAfterMs: 800, hint: '放慢、落地' },
}

/** 情绪闭集：顺序即图例顺序，也是内容校验遍历时的稳定顺序。 */
export const SPOKEN_EMOTIONS: readonly SpokenEmotion[] = Object.keys(EMOTION_SPECS) as SpokenEmotion[]

/** 单个小句上限（字）：相声没有长句。按逗号级切分，不按整行切。 */
export const CLAUSE_MAX_CHARS = 20
/** 逗哏单次发言上限（句）：超过就变成讲座了。 */
export const DOU_MAX_LINES = 5
/** 捧哏「无效附和」占比上限：全是「嗯」就没人拆台了。 */
export const PENG_FILLER_MAX_RATIO = 1 / 3
/** 每章 punch 次数闭区间：少于 2 笑不起来，多于 6 就油了。 */
export const PUNCH_MIN = 2
export const PUNCH_MAX = 6
/** 小结间隔（分钟）：走神两分钟回来要能接上，所以每 3–5 分钟必须有一个靠岸点。 */
export const RECAP_EVERY_MINUTES = 5
/** 情绪强度允许区间（§5.6 三道闸的第一道）。 */
export const EMOTION_GAIN_MIN = 0.4
export const EMOTION_GAIN_MAX = 0.7
/** 中文口播语速估算（字/秒）：只用于「这稿子大概几分钟」，不是验收指标。 */
export const CHARS_PER_SECOND = 4.5

const CLAUSE_SEPARATORS = /[，。！？；：、…,.!?;:]/
const CLAUSE_SEPARATORS_GLOBAL = /[，。！？；：、…,.!?;:]/g
/** 「说白了」是唯一的小结标记：文案单点，改它就要同步改门禁与验收口径。 */
export const RECAP_MARKER = '说白了'
/** 捧哏带问题才算推进：短句里出现这些词也算（「那数据改了呢？」）。 */
const PENG_QUESTION_WORDS = ['吗', '呢', '什么', '怎么', '哪', '为啥', '为什么', '谁', '多少', '几', '会不会', '能不能', '要不要']

/** 展平后的一句话：`pauseAfterMs` 已按情绪表解析，播放器与质检都不用再查表。 */
export interface SpokenUtterance {
  sectionId: string
  speaker: SpokenSpeaker
  emotion: SpokenEmotion
  text: string
  pauseAfterMs: number
}

/** 小节形态：缺省继承章级，混合章靠它按小节单口 / 对口。 */
export function sectionForm(chapter: SpokenChapter, section: SpokenSection): SpokenForm {
  return section.form ?? chapter.form
}

/** 按小节 → 情绪段 → 句逐层展平：时间轴、质检、字数统计都从这一份口径出发。 */
export function flattenSpoken(chapter: SpokenChapter): SpokenUtterance[] {
  const out: SpokenUtterance[] = []
  for (const section of chapter.sections) {
    for (const segment of section.segments) {
      const spec = EMOTION_SPECS[segment.emotion]
      for (const text of segment.lines) {
        out.push({
          sectionId: section.sectionId,
          speaker: segment.speaker,
          emotion: segment.emotion,
          text,
          pauseAfterMs: spec.pauseAfterMs,
        })
      }
    }
  }
  return out
}

/** 去掉空白后的字数：中文口播按字计，标点不计入语速估算。 */
export function spokenChars(chapter: SpokenChapter): number {
  return flattenSpoken(chapter).reduce((sum, u) => sum + u.text.replace(/\s/g, '').length, 0)
}

/**
 * 估算时长：字数 ÷ 语速 + 情绪停顿。
 * 这是「够不够 8 分钟」的量级判断，不是音频真实时长——真实时长以 `SpokenTrack.durationMs` 为准。
 */
export function estimateSpokenMs(chapter: SpokenChapter): number {
  let ms = 0
  for (const section of chapter.sections) {
    for (const segment of section.segments) {
      const spec = EMOTION_SPECS[segment.emotion]
      ms += spec.pauseBeforeMs
      for (const line of segment.lines) {
        ms += (line.replace(/\s/g, '').length / CHARS_PER_SECOND) * 1000 + spec.pauseAfterMs
      }
    }
  }
  return Math.round(ms)
}

export interface SpokenSummary {
  sections: number
  lines: number
  chars: number
  minutes: number
  punch: number
  recaps: number
}

/** 章节规格摘要：目录卡「听」入口与「本音频约 N 分钟」都用它，页面零计算。 */
export function summarizeSpoken(chapter: SpokenChapter): SpokenSummary {
  const utterances = flattenSpoken(chapter)
  return {
    sections: chapter.sections.length,
    lines: utterances.length,
    chars: spokenChars(chapter),
    minutes: Math.round((estimateSpokenMs(chapter) / 60000) * 10) / 10,
    punch: utterances.filter((u) => u.emotion === 'punch').length,
    recaps: utterances.filter((u) => u.text.includes(RECAP_MARKER)).length,
  }
}

/** 每章至少几个小结：按估算时长 / 5 分钟向上取整，最少 1 个。 */
export function requiredRecaps(chapter: SpokenChapter): number {
  const minutes = estimateSpokenMs(chapter) / 60000
  return Math.max(1, Math.ceil(minutes / RECAP_EVERY_MINUTES))
}

/** 按逗号级切小句：质检与「一句话太长」的修稿都按这个口径，不按整行切。 */
export function splitClauses(line: string): string[] {
  return line.split(CLAUSE_SEPARATORS).filter((clause) => clause.trim().length > 0)
}

/** 捧哏这一句算不算推进：短于 4 字且不含疑问词，就是纯附和。 */
export function isPengPromoting(text: string): boolean {
  const core = text.replace(CLAUSE_SEPARATORS_GLOBAL, '').replace(/\s/g, '')
  if (core.length >= 4) return true
  return PENG_QUESTION_WORDS.some((word) => text.includes(word))
}

export type SpokenIssueCode =
  | 'unknown_tutorial'
  | 'section_unknown'
  | 'section_missing'
  | 'section_order'
  | 'empty_section'
  | 'empty_line'
  | 'clause_too_long'
  | 'speaker_solo'
  | 'duo_missing_voice'
  | 'duo_missing_peng'
  | 'dou_turn_too_long'
  | 'peng_filler_ratio'
  | 'punch_count'
  | 'recap_missing'
  | 'emotion_gain'

/** 一条质检结论：`code` 供测试断言，`message` 是给写稿人看的中文原因与改法。 */
export interface SpokenIssue {
  code: SpokenIssueCode
  sectionId?: string
  message: string
}

/**
 * 单章质检：`tutorial` 缺省时只跳过「小节对齐」那组检查（其余文本与节奏规则照跑）。
 * 返回空数组 = 过闸。
 */
export function validateSpokenChapter(chapter: SpokenChapter, tutorial?: TutorialChapter): SpokenIssue[] {
  const issues: SpokenIssue[] = []
  const push = (code: SpokenIssueCode, message: string, sectionId?: string) => {
    issues.push(sectionId ? { code, sectionId, message } : { code, message })
  }

  const gain = chapter.voice.emotionGain
  if (gain < EMOTION_GAIN_MIN || gain > EMOTION_GAIN_MAX) {
    push('emotion_gain', `情绪强度要在 ${EMOTION_GAIN_MIN}–${EMOTION_GAIN_MAX} 之间，当前 ${gain}`)
  }
  if (chapter.form === 'duo' && !chapter.voice.support) {
    push('duo_missing_voice', '对口章必须给捧哏音色（support），且要能跟逗哏盲听区分')
  }

  if (!tutorial) {
    push('unknown_tutorial', `教程里找不到章节 ${chapter.chapterId}，口播稿会挂不上听入口`)
  } else {
    const expected = tutorial.sections.map((section) => section.id)
    const actual = chapter.sections.map((section) => section.sectionId)
    for (const id of actual) {
      if (!expected.includes(id)) {
        push('section_unknown', `小节 ${id} 不在教程 ${tutorial.title} 里`, id)
      }
    }
    for (const id of expected) {
      if (!actual.includes(id)) {
        push('section_missing', `教程小节 ${id} 还没有口播稿，听模式会断在半路`, id)
      }
    }
    const actualInOrder = actual.filter((id) => expected.includes(id))
    const expectedInOrder = expected.filter((id) => actual.includes(id))
    if (actualInOrder.join('|') !== expectedInOrder.join('|')) {
      push('section_order', '口播稿小节顺序与教程不一致，连播会跳来跳去')
    }
  }

  for (const section of chapter.sections) {
    const form = sectionForm(chapter, section)
    const utterances = flattenSpoken({ ...chapter, sections: [section] })
    if (utterances.length === 0) {
      push('empty_section', `小节 ${section.sectionId} 没有口播内容`, section.sectionId)
      continue
    }

    if (form === 'solo') {
      const outsiders = utterances.filter((u) => u.speaker !== 'narrator')
      if (outsiders.length > 0) {
        push(
          'speaker_solo',
          `小节 ${section.sectionId} 是单口，却出现了 ${outsiders[0].speaker} 发言`,
          section.sectionId,
        )
      }
    } else {
      const speakers = new Set(utterances.map((u) => u.speaker))
      if (!speakers.has('dou') || !speakers.has('peng')) {
        push('duo_missing_peng', `小节 ${section.sectionId} 是对口，逗哏与捧哏都要开口`, section.sectionId)
      }
      const peng = utterances.filter((u) => u.speaker === 'peng')
      const filler = peng.filter((u) => !isPengPromoting(u.text))
      if (peng.length > 0 && filler.length / peng.length > PENG_FILLER_MAX_RATIO) {
        push(
          'peng_filler_ratio',
          `小节 ${section.sectionId} 的捧哏有 ${filler.length}/${peng.length} 句是纯附和，要把矛盾推出来`,
          section.sectionId,
        )
      }
    }

    for (const utterance of utterances) {
      if (utterance.text.trim().length === 0) {
        push('empty_line', `小节 ${section.sectionId} 有空句，合成时会多出静音`, section.sectionId)
        continue
      }
      const long = splitClauses(utterance.text).find(
        (clause) => clause.replace(/\s/g, '').length > CLAUSE_MAX_CHARS,
      )
      if (long) {
        push(
          'clause_too_long',
          `小节 ${section.sectionId} 的「${long}」超过 ${CLAUSE_MAX_CHARS} 字，拆成两句`,
          section.sectionId,
        )
      }
    }

    let douRun: SpokenUtterance[] = []
    const flushDouRun = () => {
      if (douRun.length > DOU_MAX_LINES) {
        push(
          'dou_turn_too_long',
          `小节 ${section.sectionId} 逗哏一次说了 ${douRun.length} 句（从「${douRun[0].text}」开始），超过 ${DOU_MAX_LINES} 句就成讲座了`,
          section.sectionId,
        )
      }
      douRun = []
    }
    for (const utterance of utterances) {
      if (utterance.speaker === 'dou') {
        douRun.push(utterance)
      } else {
        flushDouRun()
      }
    }
    flushDouRun()
  }

  const all = flattenSpoken(chapter)
  const punch = all.filter((u) => u.emotion === 'punch').length
  if (punch < PUNCH_MIN || punch > PUNCH_MAX) {
    push('punch_count', `本章 punch ${punch} 次，要落在 ${PUNCH_MIN}–${PUNCH_MAX} 次之间`)
  }
  const recaps = all.filter((u) => u.text.includes(RECAP_MARKER)).length
  const need = requiredRecaps(chapter)
  if (recaps < need) {
    push('recap_missing', `本章只有 ${recaps} 个「${RECAP_MARKER}」小结，按时长约需 ${need} 个`)
  }

  return issues
}

/** 整库质检：口播稿与教程按 id 对齐，任一 issue 即视为写稿没过闸。 */
export function validateSpokenLibrary(
  scripts: readonly SpokenChapter[],
  tutorials: readonly TutorialChapter[],
): SpokenIssue[] {
  const byId = new Map(tutorials.map((chapter) => [chapter.id, chapter]))
  const issues: SpokenIssue[] = []
  for (const script of scripts) {
    const tutorial = byId.get(script.chapterId)
    issues.push(
      ...validateSpokenChapter(script, tutorial).map((issue) => ({
        ...issue,
        message: `[${script.chapterId}] ${issue.message}`,
      })),
    )
  }
  return issues
}
