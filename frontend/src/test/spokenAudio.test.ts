/**
 * 音频可用性探测层（`lib/spokenAudio.ts`）的契约测试：
 * manifest 解析必须严格（半坏的数据宁可判缺失，也不能渲染出误导性时间轴），
 * 探测层必须把网络层失败（404 / 离线）统一收敛到「素材缺失」态。
 */
import { describe, expect, it } from 'vitest'
import {
  loadSpokenAudio,
  parseSpokenManifest,
  spokenManifestUrl,
  spokenSectionDurationMs,
} from '../lib/spokenAudio'

const validManifest = {
  chapterId: 'be-distributed-consistency',
  form: 'solo',
  sampleRate: 48000,
  voice: { model: 'VoxCPM2', lead: 'solo-adult-male' },
  tracks: [
    {
      sectionId: 'concept',
      src: '/audio/be-distributed-consistency/concept.wav',
      durationMs: 61610,
      cues: [
        { startMs: 345, endMs: 2375, speaker: 'narrator', emotion: 'deadpan', text: '今天说个挺硬的话题。' },
      ],
    },
  ],
}

describe('spokenManifestUrl', () => {
  it('固定在章目录根：/audio/<chapter>/manifest.json', () => {
    expect(spokenManifestUrl('mw-cache-strategy')).toBe('/audio/mw-cache-strategy/manifest.json')
  })
})

describe('parseSpokenManifest', () => {
  it('合法 manifest 全量解析，aiGenerated 缺省兜底为 true（宁可错标不可漏标）', () => {
    const parsed = parseSpokenManifest(validManifest)
    expect(parsed).not.toBeNull()
    expect(parsed?.aiGenerated).toBe(true)
    expect(parsed?.tracks[0].cues[0].emotion).toBe('deadpan')
  })

  it('aiGenerated 显式为 false 才按 false 展示', () => {
    expect(parseSpokenManifest({ ...validManifest, aiGenerated: false })?.aiGenerated).toBe(false)
  })

  it('voice.lora / ref / note 溯源字段保留', () => {
    const parsed = parseSpokenManifest({
      ...validManifest,
      voice: { model: 'VoxCPM2 + LoRA', lora: 'gdg_v1 (step_100)', ref: 'ep3-0386.wav', note: '内部试听' },
    })
    expect(parsed?.voice.lora).toBe('gdg_v1 (step_100)')
    expect(parsed?.voice.ref).toBe('ep3-0386.wav')
  })

  it.each([
    ['null 输入', null],
    ['form 非法', { ...validManifest, form: 'lecture' }],
    ['tracks 空', { ...validManifest, tracks: [] }],
    ['voice 缺 model', { ...validManifest, voice: {} }],
    ['track 缺 src', { ...validManifest, tracks: [{ ...validManifest.tracks[0], src: undefined }] }],
    ['cue 缺 text', {
      ...validManifest,
      tracks: [{ ...validManifest.tracks[0], cues: [{ startMs: 0, endMs: 10, speaker: 'narrator' }] }],
    }],
    ['cue 说话人非法', {
      ...validManifest,
      tracks: [{ ...validManifest.tracks[0], cues: [{ startMs: 0, endMs: 10, speaker: 'ai', text: 'x' }] }],
    }],
  ])('%s → 整体判废', (_name, raw) => {
    expect(parseSpokenManifest(raw)).toBeNull()
  })
})

describe('loadSpokenAudio', () => {
  it('200 + 合法 JSON → ready', async () => {
    const fetchImpl = (async () =>
      new Response(JSON.stringify(validManifest), { status: 200 })) as typeof fetch
    const state = await loadSpokenAudio('be-distributed-consistency', fetchImpl)
    expect(state.status).toBe('ready')
  })

  it('404 → missing/not_deployed（素材未上线）', async () => {
    const fetchImpl = (async () => new Response('not found', { status: 404 })) as typeof fetch
    const state = await loadSpokenAudio('be-distributed-consistency', fetchImpl)
    expect(state).toEqual({ status: 'missing', reason: 'not_deployed' })
  })

  it('网络层异常（离线）→ missing/not_deployed，不抛错', async () => {
    const fetchImpl = (async () => {
      throw new TypeError('Failed to fetch')
    }) as unknown as typeof fetch
    const state = await loadSpokenAudio('be-distributed-consistency', fetchImpl)
    expect(state).toEqual({ status: 'missing', reason: 'not_deployed' })
  })

  it('200 但 JSON 损坏 → missing/unreadable', async () => {
    const fetchImpl = (async () => new Response('{"chapterId":', { status: 200 })) as typeof fetch
    const state = await loadSpokenAudio('be-distributed-consistency', fetchImpl)
    expect(state).toEqual({ status: 'missing', reason: 'unreadable' })
  })

  it('200 但结构非法（HTML 错误页兜不住）→ missing/unreadable', async () => {
    const fetchImpl = (async () => new Response('<html>404</html>', { status: 200 })) as typeof fetch
    const state = await loadSpokenAudio('be-distributed-consistency', fetchImpl)
    expect(state).toEqual({ status: 'missing', reason: 'unreadable' })
  })
})

describe('spokenSectionDurationMs', () => {
  it('取真实时长；查无此节返回 null', () => {
    const manifest = parseSpokenManifest(validManifest)
    expect(manifest).not.toBeNull()
    expect(spokenSectionDurationMs(manifest!, 'concept')).toBe(61610)
    expect(spokenSectionDurationMs(manifest!, 'nope')).toBeNull()
  })
})
