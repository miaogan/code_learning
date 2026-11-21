/**
 * 口播稿 → 音频计划（r150 / M1）：把 `SpokenChapter` 摊平成「合成单元」。
 *
 * 为什么要单独一层：TTS 驱动（Python）只认这份 JSON，不解析 TS、不猜停顿；
 * 播放器只认 `manifest.json`（`SpokenTrack`），两边都以「口播稿」为唯一源，
 * 改稿 → 重新导出 → 重新合成，不会出现「文案改了音频没改」。
 *
 * 合成单元 = 情绪段（同 speaker + 同 emotion 连续句），与 VERSION-PLAN §5.3 一致：
 * 按情绪段整段合成保证韵律连续，段间用情绪表给的前后停顿。
 */
import { EMOTION_SPECS, estimateSpokenMs } from './spoken'
import type { SpokenChapter, SpokenEmotion, SpokenForm, SpokenSpeaker, SpokenVoice } from './spokenTypes'

export interface AudioUnit {
  speaker: SpokenSpeaker
  emotion: SpokenEmotion
  /** 段前停顿（ms），来自情绪表。 */
  pauseBeforeMs: number
  /** 段后停顿（ms）。 */
  pauseAfterMs: number
  lines: string[]
}

export interface AudioSection {
  sectionId: string
  title: string
  /** 相对路径：内网与公网同一套代码（§5.5）。 */
  src: string
  units: AudioUnit[]
  /** 估算时长（不是音频真实时长，真实值由合成产物回填）。 */
  estimateMs: number
}

export interface AudioPlan {
  chapterId: string
  form: SpokenForm
  voice: SpokenVoice
  sections: AudioSection[]
}

/** 音频路径单点：`/audio/<chapter>/<section>.wav`（pilot 用 wav，正式版改 m4a）。 */
export function audioSrcFor(chapterId: string, sectionId: string): string {
  return `/audio/${chapterId}/${sectionId}.wav`
}

export function buildAudioPlan(chapter: SpokenChapter): AudioPlan {
  return {
    chapterId: chapter.chapterId,
    form: chapter.form,
    voice: chapter.voice,
    sections: chapter.sections.map((section) => ({
      sectionId: section.sectionId,
      title: section.title,
      src: audioSrcFor(chapter.chapterId, section.sectionId),
      units: section.segments.map((segment) => ({
        speaker: segment.speaker,
        emotion: segment.emotion,
        pauseBeforeMs: EMOTION_SPECS[segment.emotion].pauseBeforeMs,
        pauseAfterMs: EMOTION_SPECS[segment.emotion].pauseAfterMs,
        lines: segment.lines,
      })),
      estimateMs: Math.round(
        estimateSpokenMs({ ...chapter, sections: [{ ...section }] }),
      ),
    })),
  }
}
