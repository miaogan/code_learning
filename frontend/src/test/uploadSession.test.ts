import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ResumeMeta } from '../api/types'
import {
  COMPLETED_REPLAY_WINDOW_MS,
  HEIC_UNSUPPORTED_HINT,
  UPLOAD_SESSION_TTL_MS,
  clearUploadSession,
  elapsedSince,
  isHeifHeader,
  readUploadSession,
  shouldReplayCompleted,
  uploadSessionKey,
  writeUploadSession,
} from '../lib/uploadSession'

const META: ResumeMeta = {
  resume_id: 'res-r42',
  file_name: '照片简历（2 张）',
  chars: 800,
  sections: 3,
  source_type: 'image',
  image_count: 2,
}

const NOW = Date.parse('2026-11-08T10:00:00+00:00')

/** node 测试环境没有 localStorage：用 Map 装一个最小实现（与 learnProgress 测试同口径）。 */
const store = new Map<string, string>()

function installWindow(): void {
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
      removeItem: (key: string) => {
        store.delete(key)
      },
    },
  })
}

beforeEach(() => {
  store.clear()
  vi.unstubAllGlobals()
  installWindow()
})

describe('上传会话（r42 断连恢复锚点）', () => {
  it('按账号隔离存储', () => {
    expect(uploadSessionKey('u-1')).toBe('sc.upload.u-1')
    expect(uploadSessionKey(null)).toBe('sc.upload.anon')
  })

  it('写入后可读回，写入时自动补 version / saved_at', () => {
    writeUploadSession('u-1', { source: 'image', resume_job_id: 'rj-1' })
    const session = readUploadSession('u-1')
    expect(session).not.toBeNull()
    expect(session?.version).toBe(1)
    expect(session?.source).toBe('image')
    expect(session?.resume_job_id).toBe('rj-1')
    expect(typeof session?.saved_at).toBe('string')
    // 另一个账号看不到
    expect(readUploadSession('u-2')).toBeNull()
  })

  it('超过 24 小时自动失效并清掉脏数据', () => {
    writeUploadSession('u-1', { source: 'file', profile_job_id: 'pj-1', meta: META })
    const saved = readUploadSession('u-1')
    expect(saved).not.toBeNull()
    // 把 saved_at 改成 25 小时前
    store.set(
      uploadSessionKey('u-1'),
      JSON.stringify({ ...saved, saved_at: new Date(NOW - UPLOAD_SESSION_TTL_MS - 1000).toISOString() }),
    )
    expect(readUploadSession('u-1', NOW)).toBeNull()
    expect(store.get(uploadSessionKey('u-1'))).toBeUndefined()
  })

  it('结构不合法（版本 / 来源 / 时间错）按无会话处理', () => {
    store.set(
      uploadSessionKey('u-1'),
      JSON.stringify({ version: 2, source: 'image', saved_at: '2026-11-08T10:00:00+00:00' }),
    )
    expect(readUploadSession('u-1', NOW)).toBeNull()
  })

  it('清会话只清自己的账号', () => {
    writeUploadSession('u-1', { source: 'image', resume_job_id: 'rj-1' })
    writeUploadSession('u-2', { source: 'image', resume_job_id: 'rj-2' })
    clearUploadSession('u-1')
    expect(readUploadSession('u-1')).toBeNull()
    expect(readUploadSession('u-2')?.resume_job_id).toBe('rj-2')
  })
})

describe('完成态回放窗口', () => {
  it('30 分钟内的完成才回放，更早的不打扰', () => {
    expect(COMPLETED_REPLAY_WINDOW_MS).toBe(30 * 60 * 1000)
    expect(shouldReplayCompleted('2026-11-08T09:45:00+00:00', NOW)).toBe(true)
    expect(shouldReplayCompleted('2026-11-08T09:29:00+00:00', NOW)).toBe(false)
    expect(shouldReplayCompleted('not-a-time', NOW)).toBe(false)
  })

  it('已用秒数从任务起点起算，时间不可解按 0', () => {
    expect(elapsedSince('2026-11-08T09:58:00+00:00', NOW)).toBe(120)
    expect(elapsedSince('', NOW)).toBe(0)
    expect(elapsedSince('2026-11-08T11:00:00+00:00', NOW)).toBe(0)
  })
})

describe('HEIC 真实字节识别', () => {
  function bytes(...parts: Array<number | string>): Uint8Array {
    const values: number[] = []
    for (const part of parts) {
      if (typeof part === 'number') values.push(part)
      else for (const char of part) values.push(char.charCodeAt(0))
    }
    return new Uint8Array(values)
  }

  it('major brand = heic / mif1 都判 HEIC', () => {
    expect(isHeifHeader(bytes(0, 0, 0, 24, 'ftyp', 'heic', 0, 0, 0, 0, 'mif1'))).toBe(true)
    expect(isHeifHeader(bytes(0, 0, 0, 24, 'ftyp', 'mif1', 0, 0, 0, 0, 'mif1'))).toBe(true)
  })

  it('兼容品牌里出现 heic 也判 HEIC', () => {
    expect(isHeifHeader(bytes(0, 0, 0, 28, 'ftyp', 'mp42', 0, 0, 0, 0, 'heic'))).toBe(true)
  })

  it('真实 HEIC 样本头部（major brand=mif1，兼容品牌 heic/hevc）判 HEIC', () => {
    // 取自 libheif 的真实样本 example.heic（下载后只读前 32 字节，不入库）。
    expect(isHeifHeader(bytes(0, 0, 0, 0x1c, 'ftyp', 'mif1', 0, 0, 0, 0, 'mif1', 'heic', 'hevc'))).toBe(
      true,
    )
  })

  it('JPEG / PNG / 过短字节不误判', () => {
    expect(isHeifHeader(bytes(0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0))).toBe(false)
    expect(isHeifHeader(bytes(0x89, 'PNG', 0x0d, 0x0a, 0x1a, 0x0a))).toBe(false)
    expect(isHeifHeader(bytes(0, 0, 0))).toBe(false)
  })

  it('提示里有可行的替代路径，不是死胡同文案', () => {
    expect(HEIC_UNSUPPORTED_HINT).toContain('HEIC')
    expect(HEIC_UNSUPPORTED_HINT).toContain('兼容性最佳')
    expect(HEIC_UNSUPPORTED_HINT).toContain('JPG')
  })
})
