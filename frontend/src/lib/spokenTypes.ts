/**
 * 有声书口播稿的数据结构（r150 / M1）。
 *
 * 音频是**离线预生成的发布资产**（运行期禁止调 TTS）：本文件只描述「文本 + 情绪 + 停顿」，
 * 不含音频字节、不含 Key、不含任何运行期出网参数。
 * 若将来要进后端契约，字段必须按 AGENTS.md 改成 snake_case 并双侧同步——
 * 当前它只在「内容文件 ↔ 离线工具链 ↔ 播放器」三者之间流转，不进 HTTP。
 */

/**
 * 情绪闭集（7 类，按相声表演设计）：句级标注，来自口播稿生成阶段。
 * 之所以是闭集而不是自由文本，是因为它要一对一到合成期的 instruct 模板与停顿表。
 */
export type SpokenEmotion =
  | 'banter'
  | 'setup'
  | 'deadpan'
  | 'punch'
  | 'realize'
  | 'contrast'
  | 'wrap'

/** 说话人：单口只有 narrator，对口是 dou（逗哏）/ peng（捧哏）。 */
export type SpokenSpeaker = 'dou' | 'peng' | 'narrator'

/** 叙事形态：单口自问自答（概念章）/ 对口抬杠（场景章）。 */
export type SpokenForm = 'solo' | 'duo'

/**
 * 情绪段：同 speaker + 同情绪连续的多句，整段合成保证段内韵律连续（VERSION-PLAN §5.3）。
 * 段内不再携带逐句停顿——停顿策略表按情绪给，逐句覆盖只会让两处口径打架。
 */
export interface SpokenSegment {
  speaker: SpokenSpeaker
  emotion: SpokenEmotion
  lines: string[]
}

/**
 * 一小节的口播稿。`form` 缺省继承章级：混合章（A+B）按小节拆，
 * 概念小节单口、场景小节对口（VERSION-PLAN §5.7 分派规则）。
 */
export interface SpokenSection {
  /** 与 `TutorialSection.id` 逐字对应：听模式的句级高亮按它定位，错一个字符就对不上。 */
  sectionId: string
  title: string
  form?: SpokenForm
  segments: SpokenSegment[]
}

/** 音色与合成参数：制作期参数，运行期只用于图例与「本音频由 X 生成」标注。 */
export interface SpokenVoice {
  /** 合成模型（如 CosyVoice2-0.5B）：音色可商用开源模型，见 §5.4。 */
  model: string
  /** 情绪强度（0.4–0.7）：相声起 0.55，讲概念压到 0.4 防朗诵腔。 */
  emotionGain: number
  /** 逗哏（或单口主讲）音色。 */
  lead: string
  /** 捧哏音色：对口必填，且必须与 lead 盲听可辨。 */
  support?: string
}

/** 一章的口播稿：章 id 与 `TutorialChapter.id` 对齐。 */
export interface SpokenChapter {
  chapterId: string
  form: SpokenForm
  /** 脚本版本号：内容改动即升，用来判断音频是否过期（§5.5 的 hash 绑定同源）。 */
  scriptVersion: string
  voice: SpokenVoice
  sections: SpokenSection[]
}

/**
 * 句级时间轴：离线工具链（VAD 切句）产出，运行期只读。
 * `text` 与口播稿逐字一致，播放器靠它在句级高亮与断点续听之间对齐。
 */
export interface SpokenCue {
  startMs: number
  endMs: number
  speaker: SpokenSpeaker
  text: string
}

/** 一小节的音频资产：**每小节一个文件**（首屏拉取小、天然支持 Range 拖动），见 §5.3。 */
export interface SpokenTrack {
  sectionId: string
  /** 相对路径（`/audio/<chapter>/<section>.m4a`）：内网与公网同一套代码。 */
  src: string
  durationMs: number
  cues: SpokenCue[]
}
