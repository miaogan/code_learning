import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  INTERVIEW_SESSION_TTL_MS,
  clearInterviewSession,
  interviewSessionKey,
  readInterviewSession,
  writeInterviewSession,
} from '../lib/interviewSession'

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

describe('面试会话本地锚点', () => {
  it('按账号隔离存储', () => {
    expect(interviewSessionKey('u-1')).toBe('sc.interview.u-1')
    expect(interviewSessionKey(null)).toBe('sc.interview.anon')
  })

  it('写入后可读回 run_id，写入时自动补 version / saved_at', () => {
    writeInterviewSession('u-1', 'run-1')
    expect(readInterviewSession('u-1')).toBe('run-1')
    const raw = JSON.parse(store.get(interviewSessionKey('u-1')) ?? '{}') as {
      version?: unknown
      saved_at?: unknown
    }
    expect(raw.version).toBe(1)
    expect(typeof raw.saved_at).toBe('string')
  })

  it('账号未就绪（userId 为空）不写，避免落到共享的 anon 键', () => {
    writeInterviewSession(null, 'run-1')
    expect(store.get(interviewSessionKey(null))).toBeUndefined()
    expect(readInterviewSession(null)).toBeNull()
  })

  it('超过有效期自动失效并清掉旧记录', () => {
    writeInterviewSession('u-1', 'run-1')
    const saved = JSON.parse(store.get(interviewSessionKey('u-1')) ?? '{}') as { saved_at: string }
    const later = Date.parse(saved.saved_at) + INTERVIEW_SESSION_TTL_MS + 1000
    expect(readInterviewSession('u-1', later)).toBeNull()
    expect(store.get(interviewSessionKey('u-1'))).toBeUndefined()
  })

  it('结构不合法 / 非 JSON 一律返回 null 并清掉脏数据', () => {
    store.set(interviewSessionKey('u-1'), '{"version":2,"run_id":"run-1"}')
    expect(readInterviewSession('u-1')).toBeNull()
    expect(store.get(interviewSessionKey('u-1'))).toBeUndefined()

    store.set(interviewSessionKey('u-1'), 'not-json')
    expect(readInterviewSession('u-1')).toBeNull()
    expect(store.get(interviewSessionKey('u-1'))).toBeUndefined()
  })

  it('清空后读不到，且清空幂等', () => {
    writeInterviewSession('u-1', 'run-1')
    clearInterviewSession('u-1')
    expect(readInterviewSession('u-1')).toBeNull()
    clearInterviewSession('u-1')
  })
})
