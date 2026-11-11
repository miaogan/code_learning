import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  INTERVIEW_DRAFT_TTL_MS,
  clearInterviewDraft,
  interviewDraftKey,
  readInterviewDraft,
  writeInterviewDraft,
} from '../lib/interviewDraft'

const NOW = Date.parse('2026-11-11T10:00:00Z')
const store = new Map<string, string>()
let failWrite = false

beforeEach(() => {
  store.clear()
  failWrite = false
  vi.unstubAllGlobals()
  vi.spyOn(Date, 'now').mockReturnValue(NOW)
  vi.setSystemTime(NOW)
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        if (failWrite) throw new Error('quota')
        store.set(key, value)
      },
      removeItem: (key: string) => store.delete(key),
    },
  })
})

describe('r75 面试回答草稿', () => {
  it('只恢复当前场次与当前题', () => {
    writeInterviewDraft('u1', { runId: 'r1', questionId: 'iq-1', text: '我的回答' })
    expect(readInterviewDraft('u1', 'r1', 'iq-1', NOW)).toMatchObject({ status: 'ok', text: '我的回答' })
    expect(readInterviewDraft('u1', 'r1', 'iq-2', NOW)).toEqual({ status: 'none' })
    expect(readInterviewDraft('u1', 'r2', 'iq-1', NOW)).toEqual({ status: 'none' })
    expect(readInterviewDraft('u2', 'r1', 'iq-1', NOW)).toEqual({ status: 'none' })
  })

  it('匿名不写，存储失败返回 false', () => {
    expect(writeInterviewDraft(null, { runId: 'r1', questionId: 'q1', text: 'x' })).toBe(false)
    failWrite = true
    expect(writeInterviewDraft('u1', { runId: 'r1', questionId: 'q1', text: 'x' })).toBe(false)
  })

  it('空文本清除旧草稿', () => {
    writeInterviewDraft('u1', { runId: 'r1', questionId: 'q1', text: 'x' })
    expect(writeInterviewDraft('u1', { runId: 'r1', questionId: 'q1', text: '' })).toBe(true)
    expect(store.has(interviewDraftKey('u1', 'r1'))).toBe(false)
  })

  it('读取时按作答器上限截断', () => {
    writeInterviewDraft('u1', { runId: 'r1', questionId: 'q1', text: 'x'.repeat(900) })
    const read = readInterviewDraft('u1', 'r1', 'q1', NOW)
    expect(read.status).toBe('ok')
    if (read.status === 'ok') expect(read.text).toHaveLength(800)
  })

  it('超过 24 小时返回 expired', () => {
    writeInterviewDraft('u1', { runId: 'r1', questionId: 'q1', text: 'x' })
    const key = interviewDraftKey('u1', 'r1')
    const value = JSON.parse(store.get(key)!) as object
    store.set(key, JSON.stringify({ ...value, saved_at: new Date(NOW - INTERVIEW_DRAFT_TTL_MS - 1).toISOString() }))
    expect(readInterviewDraft('u1', 'r1', 'q1', NOW)).toEqual({ status: 'expired' })
  })

  it('损坏 JSON 与版本不符返回 invalid', () => {
    store.set(interviewDraftKey('u1', 'r1'), '{bad')
    expect(readInterviewDraft('u1', 'r1', 'q1', NOW)).toEqual({ status: 'invalid' })
    store.set(interviewDraftKey('u1', 'r1'), JSON.stringify({ version: 2 }))
    expect(readInterviewDraft('u1', 'r1', 'q1', NOW)).toEqual({ status: 'invalid' })
  })

  it('未来时间戳拒绝恢复', () => {
    writeInterviewDraft('u1', { runId: 'r1', questionId: 'q1', text: 'x' })
    const key = interviewDraftKey('u1', 'r1')
    const value = JSON.parse(store.get(key)!) as object
    store.set(key, JSON.stringify({ ...value, saved_at: new Date(NOW + 10 * 60_000).toISOString() }))
    expect(readInterviewDraft('u1', 'r1', 'q1', NOW)).toEqual({ status: 'invalid' })
  })

  it('清除后返回 none，清理失败不抛出', () => {
    writeInterviewDraft('u1', { runId: 'r1', questionId: 'q1', text: 'x' })
    clearInterviewDraft('u1', 'r1')
    expect(readInterviewDraft('u1', 'r1', 'q1', NOW)).toEqual({ status: 'none' })
    vi.stubGlobal('window', { localStorage: { removeItem: () => { throw new Error('blocked') } } })
    expect(() => clearInterviewDraft('u1', 'r1')).not.toThrow()
  })
})
