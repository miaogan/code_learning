/**
 * 播放器纯逻辑（`lib/spokenPlayer.ts`）的契约测试：
 * 句级定位、断点有效性守卫、localStorage 存取——这些逻辑错了会直接变成「高亮乱跳」和「断点复活旧章」。
 */
import { describe, expect, it } from 'vitest'
import {
  PLAYBACK_SPEEDS,
  activeCueIndex,
  formatMs,
  listenStorageKey,
  loadListenResume,
  parseListenResume,
  saveListenResume,
  serializeListenResume,
  validResume,
  type ListenResume,
} from '../lib/spokenPlayer'
import type { SpokenAudioCue } from '../lib/spokenAudio'

const cues: SpokenAudioCue[] = [
  { startMs: 0, endMs: 2000, speaker: 'narrator', text: '第一句' },
  { startMs: 2400, endMs: 4400, speaker: 'narrator', text: '第二句' },
  { startMs: 5000, endMs: 7000, speaker: 'peng', text: '第三句' },
]

describe('PLAYBACK_SPEEDS', () => {
  it('0.75–2.0 档位（VERSION-PLAN §4.1），升序排列', () => {
    expect(PLAYBACK_SPEEDS[0]).toBe(0.75)
    expect(PLAYBACK_SPEEDS[PLAYBACK_SPEEDS.length - 1]).toBe(2)
    for (let i = 1; i < PLAYBACK_SPEEDS.length; i += 1) {
      expect(PLAYBACK_SPEEDS[i]).toBeGreaterThan(PLAYBACK_SPEEDS[i - 1])
    }
  })
})

describe('formatMs', () => {
  it('m:ss 口径；非法输入归零', () => {
    expect(formatMs(0)).toBe('0:00')
    expect(formatMs(61610)).toBe('1:01')
    expect(formatMs(-5)).toBe('0:00')
    expect(formatMs(Number.NaN)).toBe('0:00')
  })
})

describe('activeCueIndex', () => {
  it('命中句内返回该句下标', () => {
    expect(activeCueIndex(cues, 1000)).toBe(0)
    expect(activeCueIndex(cues, 3000)).toBe(1)
    expect(activeCueIndex(cues, 6000)).toBe(2)
  })

  it('句间停顿停在刚说完的句（高亮不闪空）', () => {
    expect(activeCueIndex(cues, 2200)).toBe(0)
    expect(activeCueIndex(cues, 4700)).toBe(1)
  })

  it('开头前与结尾后不返回 -1', () => {
    expect(activeCueIndex(cues, -1)).toBe(0)
    expect(activeCueIndex(cues, 99999)).toBe(2)
  })

  it('空 cue 列表安全返回 0', () => {
    expect(activeCueIndex([], 1000)).toBe(0)
  })
})

describe('validResume', () => {
  const sectionIds = ['concept', 'patterns']

  it('合法断点原样通过', () => {
    const resume: ListenResume = { sectionId: 'patterns', positionMs: 5000 }
    expect(validResume(resume, sectionIds, 61610)).toEqual(resume)
  })

  it.each([
    ['小节已不存在（章节改版）', { sectionId: 'deleted', positionMs: 5000 }],
    ['位置非正数', { sectionId: 'concept', positionMs: 0 }],
    ['位置 NaN', { sectionId: 'concept', positionMs: Number.NaN }],
    ['位置超出时长（音频已换版）', { sectionId: 'concept', positionMs: 99999 }],
  ])('%s → 无效断点', (_name, resume) => {
    expect(validResume(resume as ListenResume, sectionIds, 61610)).toBeNull()
  })

  it('时长未知（manifest 未带）时只验小节与正数', () => {
    expect(validResume({ sectionId: 'concept', positionMs: 12345 }, sectionIds, undefined)).toEqual({
      sectionId: 'concept',
      positionMs: 12345,
    })
  })

  it('null 输入直接无效', () => {
    expect(validResume(null, sectionIds, undefined)).toBeNull()
  })
})

describe('localStorage 存取', () => {
  class MemoryStorage {
    private map = new Map<string, string>()
    getItem(key: string): string | null {
      return this.map.get(key) ?? null
    }
    setItem(key: string, value: string): void {
      this.map.set(key, value)
    }
  }

  it('存取回环一致', () => {
    const storage = new MemoryStorage()
    const resume: ListenResume = { sectionId: 'concept', positionMs: 1234.6 }
    saveListenResume(storage, 'k', resume)
    expect(loadListenResume(storage, 'k')).toEqual({ sectionId: 'concept', positionMs: 1235 })
  })

  it('存储为 null（SSR / 测试环境）时静默降级', () => {
    const resume: ListenResume = { sectionId: 'concept', positionMs: 1000 }
    expect(() => saveListenResume(null, 'k', resume)).not.toThrow()
    expect(loadListenResume(null, 'k')).toBeNull()
  })

  it('损坏数据返回 null，不抛错', () => {
    const storage = new MemoryStorage()
    storage.setItem('k', '{broken')
    expect(loadListenResume(storage, 'k')).toBeNull()
    storage.setItem('k2', '["not","an","object"]')
    expect(loadListenResume(storage, 'k2')).toBeNull()
  })

  it('序列化口径固定（字段名 short，供跨版本兼容判断）', () => {
    expect(serializeListenResume({ sectionId: 'concept', positionMs: 1500 })).toBe(
      '{"section":"concept","ms":1500}',
    )
    expect(parseListenResume('{"section":"concept","ms":1500}')).toEqual({
      sectionId: 'concept',
      positionMs: 1500,
    })
    expect(parseListenResume(null)).toBeNull()
  })
})

describe('listenStorageKey', () => {
  it('与 learnProgress 同款分区：匿名裸前缀，登录按用户后缀', () => {
    expect(listenStorageKey(null, 'be-distributed-consistency')).toBe(
      'sc.listen.be-distributed-consistency',
    )
    expect(listenStorageKey('u1', 'be-distributed-consistency')).toBe('sc.listen.u1.be-distributed-consistency')
  })
})
