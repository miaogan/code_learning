/**
 * 音频资产的运行期探测层（r151）：播放器不内置「哪章有音频」的清单，
 * 而是按约定路径拉 `/audio/<chapter>/manifest.json`（离线工具链 `synthesize.py` 的产物）。
 *
 * 为什么不把「有音频的章」写死在代码里：音频是**部署期资产**（用户明确要求：
 * 等找到合法素材后放到服务器、经 nginx 提供）——素材上线只往服务器挂卷里放文件，
 * 前端零改动、零发版。manifest 拉不到（404 / 解析失败）就是「素材缺失」态，
 * 播放器据此渲染口播稿浏览视图，绝不渲染一个点了没声音的空播放器。
 *
 * r151 全量流水线追加：`/audio/index.json`（make_audio.py 聚合所有章 manifest）是
 * 「听听」入口的唯一真源——新章音频部署后入口自动出现，覆盖所有文字与后续新知识。
 *
 * AI 标识（RELEASE-DATA-SOP 合规红线 #4）：`aiGenerated` 缺省按 `true` 处理——
 * 宁可错标、不可漏标；manifest 里显式写了才允许按 false 展示。
 */
import { useEffect, useState } from 'react'
import type { SpokenCue, SpokenForm, SpokenSpeaker } from './spokenTypes'

/** manifest 里的音色块：比 `SpokenVoice` 多 lora / ref / note（制作期溯源信息）。 */
export interface SpokenAudioVoiceInfo {
  model: string
  lead?: string
  support?: string
  lora?: string
  ref?: string
  note?: string
}

/** cue 的 manifest 口径：比 `SpokenCue` 多情绪（播放器高亮样式要用）。 */
export interface SpokenAudioCue extends SpokenCue {
  emotion?: string
}

/** manifest 里的单轨：与 `synthesize.py` 落盘结构逐字对应。 */
export interface SpokenAudioTrack {
  sectionId: string
  src: string
  /** 可读小节标题（工具链从 plans 带出；缺省回落 sectionId）。 */
  title?: string
  durationMs: number
  sampleRate?: number
  cues: SpokenAudioCue[]
}

/** 生产 manifest 的完整结构。`aiGenerated` 由工具链写入（旧产物缺省也按 true）。 */
export interface SpokenAudioManifest {
  chapterId: string
  form: SpokenForm
  sampleRate: number
  voice: SpokenAudioVoiceInfo
  aiGenerated: boolean
  tracks: SpokenAudioTrack[]
}

/** 播放器对一章音频的三态：loading 探测中 / ready 可播 / missing 素材缺失。 */
export type SpokenAudioState =
  | { status: 'loading' }
  | { status: 'missing'; reason: 'not_deployed' | 'unreadable' }
  | { status: 'ready'; manifest: SpokenAudioManifest }

/** 音频路径单点（与 `audioSrcFor` 同口径）：manifest 固定在章目录根。 */
export function spokenManifestUrl(chapterId: string): string {
  return `/audio/${chapterId}/manifest.json`
}

function isSpeaker(value: unknown): value is SpokenSpeaker {
  return value === 'dou' || value === 'peng' || value === 'narrator'
}

/**
 * 严格解析 manifest：结构不对就整体判废（返回 `null` 走缺失态），
 * 不做「缺字段补默认值」的宽松解析——半坏的 manifest 渲染出的时间轴比缺失更误导。
 */
export function parseSpokenManifest(raw: unknown): SpokenAudioManifest | null {
  if (raw === null || typeof raw !== 'object') return null
  const data = raw as Record<string, unknown>
  if (typeof data.chapterId !== 'string' || typeof data.sampleRate !== 'number') return null
  if (data.form !== 'solo' && data.form !== 'duo') return null
  if (!Array.isArray(data.tracks) || data.tracks.length === 0) return null

  const voiceRaw = (data.voice ?? {}) as Record<string, unknown>
  if (typeof voiceRaw.model !== 'string') return null

  const tracks: SpokenAudioTrack[] = []
  for (const item of data.tracks) {
    if (item === null || typeof item !== 'object') return null
    const track = item as Record<string, unknown>
    if (typeof track.sectionId !== 'string' || typeof track.src !== 'string') return null
    if (typeof track.durationMs !== 'number' || !Array.isArray(track.cues)) return null
    const cues: SpokenAudioCue[] = []
    for (const cueRaw of track.cues) {
      if (cueRaw === null || typeof cueRaw !== 'object') return null
      const cue = cueRaw as Record<string, unknown>
      if (
        typeof cue.startMs !== 'number' ||
        typeof cue.endMs !== 'number' ||
        !isSpeaker(cue.speaker) ||
        typeof cue.text !== 'string'
      ) {
        return null
      }
      cues.push({
        startMs: cue.startMs,
        endMs: cue.endMs,
        speaker: cue.speaker,
        text: cue.text,
        emotion: typeof cue.emotion === 'string' ? cue.emotion : undefined,
      })
    }
    tracks.push({
      sectionId: track.sectionId,
      src: track.src,
      title: typeof track.title === 'string' ? track.title : undefined,
      durationMs: track.durationMs,
      sampleRate: typeof track.sampleRate === 'number' ? track.sampleRate : undefined,
      cues,
    })
  }

  const voice: SpokenAudioVoiceInfo = { model: voiceRaw.model }
  if (typeof voiceRaw.lead === 'string') voice.lead = voiceRaw.lead
  if (typeof voiceRaw.support === 'string') voice.support = voiceRaw.support
  if (typeof voiceRaw.lora === 'string') voice.lora = voiceRaw.lora
  if (typeof voiceRaw.ref === 'string') voice.ref = voiceRaw.ref
  if (typeof voiceRaw.note === 'string') voice.note = voiceRaw.note

  return {
    chapterId: data.chapterId,
    form: data.form,
    sampleRate: data.sampleRate,
    voice,
    // 缺省即 AI 生成：宁可错标、不可漏标（SOP 红线 #4 的运行期兜底）。
    aiGenerated: data.aiGenerated === undefined ? true : data.aiGenerated === true,
    tracks,
  }
}

/** 探测一章音频。`fetchImpl` 仅为测试注入，运行期用全局 fetch。 */
export async function loadSpokenAudio(
  chapterId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<SpokenAudioState> {
  let response: Response
  try {
    response = await fetchImpl(spokenManifestUrl(chapterId))
  } catch {
    // 网络层失败（离线 / DNS）：按「未部署」处理，不区分原因——两者都渲染缺失态。
    return { status: 'missing', reason: 'not_deployed' }
  }
  if (!response.ok) return { status: 'missing', reason: 'not_deployed' }
  try {
    const manifest = parseSpokenManifest(await response.json())
    if (manifest === null) return { status: 'missing', reason: 'unreadable' }
    return { status: 'ready', manifest }
  } catch {
    return { status: 'missing', reason: 'unreadable' }
  }
}

/** 章内某一节的小节时长：音频真实时长以 manifest 为准（estimate 只是估算）。 */
export function spokenSectionDurationMs(
  manifest: SpokenAudioManifest,
  sectionId: string,
): number | null {
  return manifest.tracks.find((track) => track.sectionId === sectionId)?.durationMs ?? null
}

/* ---------- r151 全量流水线：/audio/index.json（新章部署后入口自动出现） ---------- */

/** 索引里的一章（与 make_audio.py / synthesize.py 聚合产物同构）。 */
export interface SpokenAudioIndexEntry {
  chapterId: string
  title: string
  form: SpokenForm
  aiGenerated: boolean
  sections: { sectionId: string; title: string; durationMs: number }[]
  totalMs: number
}

export interface SpokenAudioIndex {
  generatedAt: string
  chapters: SpokenAudioIndexEntry[]
}

/** 索引路径单点：章目录的上一层。 */
export function spokenAudioIndexUrl(): string {
  return '/audio/index.json'
}

/** 严格解析索引；半坏数据整体判废（入口多显示一章比 404 播放器好，但脏数据不行）。 */
export function parseSpokenAudioIndex(raw: unknown): SpokenAudioIndex | null {
  if (raw === null || typeof raw !== 'object') return null
  const data = raw as Record<string, unknown>
  if (!Array.isArray(data.chapters)) return null
  const chapters: SpokenAudioIndexEntry[] = []
  for (const item of data.chapters) {
    if (item === null || typeof item !== 'object') return null
    const entry = item as Record<string, unknown>
    if (
      typeof entry.chapterId !== 'string' ||
      typeof entry.title !== 'string' ||
      (entry.form !== 'solo' && entry.form !== 'duo') ||
      !Array.isArray(entry.sections)
    ) {
      return null
    }
    const sections: SpokenAudioIndexEntry['sections'] = []
    for (const secRaw of entry.sections) {
      if (secRaw === null || typeof secRaw !== 'object') return null
      const sec = secRaw as Record<string, unknown>
      if (
        typeof sec.sectionId !== 'string' ||
        typeof sec.title !== 'string' ||
        typeof sec.durationMs !== 'number'
      ) {
        return null
      }
      sections.push({ sectionId: sec.sectionId, title: sec.title, durationMs: sec.durationMs })
    }
    chapters.push({
      chapterId: entry.chapterId,
      title: entry.title,
      form: entry.form,
      aiGenerated: entry.aiGenerated === undefined ? true : entry.aiGenerated === true,
      sections,
      totalMs: typeof entry.totalMs === 'number' ? entry.totalMs : 0,
    })
  }
  return {
    generatedAt: typeof data.generatedAt === 'string' ? data.generatedAt : '',
    chapters,
  }
}

/** 拉全量音频索引；网络层失败 / 404 / 脏数据统一返回 `null`（=没有任何章有音频）。 */
export async function loadAudioIndex(fetchImpl: typeof fetch = fetch): Promise<SpokenAudioIndex | null> {
  let response: Response
  try {
    response = await fetchImpl(spokenAudioIndexUrl())
  } catch {
    return null
  }
  if (!response.ok) return null
  try {
    return parseSpokenAudioIndex(await response.json())
  } catch {
    return null
  }
}

let indexCache: SpokenAudioIndex | null | undefined

/** 入口判断用的索引 hook：模块级缓存（一次会话只拉一次；404 页/null 也缓存，不反复探测）。 */
export function useSpokenAudioIndex(): SpokenAudioIndex | null {
  const [index, setIndex] = useState<SpokenAudioIndex | null>(() => indexCache ?? null)
  useEffect(() => {
    if (indexCache !== undefined) {
      setIndex(indexCache)
      return
    }
    let cancelled = false
    void loadAudioIndex().then((result) => {
      indexCache = result
      if (!cancelled) setIndex(result)
    })
    return () => {
      cancelled = true
    }
  }, [])
  return index
}

/** 某章是否有已部署音频（入口判断的唯一依据）。 */
export function audioIndexHasChapter(
  index: SpokenAudioIndex | null,
  chapterId: string,
): boolean {
  return index?.chapters.some((entry) => entry.chapterId === chapterId) ?? false
}
