/**
 * 音频可用性探测层（`lib/spokenAudio.ts`）的契约测试：
 * manifest 解析必须严格（半坏的数据宁可判缺失，也不能渲染出误导性时间轴），
 * 探测层必须把网络层失败（404 / 离线）统一收敛到「素材缺失」态。
 */
import { describe, expect, it } from 'vitest'
import {
  audioIndexHasChapter,
  loadAudioIndex,
  loadSpokenAudio,
  parseSpokenAudioIndex,
  parseSpokenManifest,
  spokenAudioIndexUrl,
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

/* ---------- r151 全量流水线：/audio/index.json（入口真源） ---------- */

const validIndex = {
  generatedAt: '2026-11-23T10:00:00Z',
  chapters: [
    {
      chapterId: 'fe-react-render',
      title: 'React 状态与渲染',
      form: 'duo',
      aiGenerated: true,
      sections: [
        { sectionId: 'concept', title: '状态驱动的渲染模型', durationMs: 45000 },
        { sectionId: 'pitfall', title: '闭包陷阱', durationMs: 38000 },
      ],
      totalMs: 83000,
    },
    {
      chapterId: 'mw-cache-strategy',
      title: '缓存策略',
      form: 'solo',
      sections: [{ sectionId: 'concept', title: '缓存失效', durationMs: 30000 }],
      totalMs: 30000,
    },
  ],
}

describe('spokenAudioIndexUrl', () => {
  it('固定在 /audio/index.json（章目录的上一层）', () => {
    expect(spokenAudioIndexUrl()).toBe('/audio/index.json')
  })
})

describe('parseSpokenAudioIndex', () => {
  it('合法索引全量解析；aiGenerated 缺省兜底为 true（宁可错标不可漏标）', () => {
    const parsed = parseSpokenAudioIndex(validIndex)
    expect(parsed).not.toBeNull()
    expect(parsed?.chapters).toHaveLength(2)
    expect(parsed?.chapters[1].aiGenerated).toBe(true)
    expect(parsed?.chapters[0].sections[0].title).toBe('状态驱动的渲染模型')
  })

  it.each([
    ['null 输入', null],
    ['缺 chapters 数组', { generatedAt: 'x' }],
    ['chapters 非数组', { chapters: 'two' }],
    ['章缺 title', { chapters: [{ ...validIndex.chapters[0], title: undefined }] }],
    ['章 form 非法', { chapters: [{ ...validIndex.chapters[0], form: 'lecture' }] }],
    ['小节缺 durationMs', {
      chapters: [{
        ...validIndex.chapters[0],
        sections: [{ sectionId: 'concept', title: 'x' }],
      }],
    }],
    ['数组里混入 null', { chapters: [...validIndex.chapters, null] }],
  ])('%s → 整体判废（半坏索引比没有索引更误导）', (_name, raw) => {
    expect(parseSpokenAudioIndex(raw)).toBeNull()
  })
})

describe('loadAudioIndex', () => {
  it('200 + 合法 JSON → 索引', async () => {
    const fetchImpl = (async () =>
      new Response(JSON.stringify(validIndex), { status: 200 })) as typeof fetch
    const index = await loadAudioIndex(fetchImpl)
    expect(index?.chapters).toHaveLength(2)
  })

  it('404（素材还没部署）→ null，不抛错', async () => {
    const fetchImpl = (async () => new Response('not found', { status: 404 })) as typeof fetch
    expect(await loadAudioIndex(fetchImpl)).toBeNull()
  })

  it('网络层异常（离线）→ null', async () => {
    const fetchImpl = (async () => {
      throw new TypeError('Failed to fetch')
    }) as unknown as typeof fetch
    expect(await loadAudioIndex(fetchImpl)).toBeNull()
  })

  it('200 但结构非法（HTML 错误页兜不住）→ null', async () => {
    const fetchImpl = (async () => new Response('<html>404</html>', { status: 200 })) as typeof fetch
    expect(await loadAudioIndex(fetchImpl)).toBeNull()
  })
})

describe('audioIndexHasChapter', () => {
  const index = parseSpokenAudioIndex(validIndex)
  it('索引里有 → true', () => {
    expect(audioIndexHasChapter(index, 'fe-react-render')).toBe(true)
  })
  it('索引里没有 → false', () => {
    expect(audioIndexHasChapter(index, 'not-a-chapter')).toBe(false)
  })
  it('索引还没拉回来（null）→ false（入口先不亮，内侧了再来就有）', () => {
    expect(audioIndexHasChapter(null, 'fe-react-render')).toBe(false)
  })
})
