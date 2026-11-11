import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExamRun } from '../api/types'
import {
  EXAM_DRAFT_TTL_MS,
  clearExamDraft,
  examDraftKey,
  readExamDraft,
  writeExamDraft,
} from '../lib/examDraft'

const NOW = Date.parse('2026-11-11T10:00:00Z')
const RUN: ExamRun = {
  run_id: 'exam-1',
  questions: [
    { id: 'q1', kind: 'single', direction: '后端', prompt: '题一', options: [] },
    { id: 'q2', kind: 'multiple', direction: '后端', prompt: '题二', options: [] },
  ],
  filtered_count: 0,
  reintroduced_count: 0,
  sub_direction: '',
  sub_direction_backfill: 0,
}
const store = new Map<string, string>()
let failWrite = false

function installWindow(): void {
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
}

beforeEach(() => {
  store.clear()
  failWrite = false
  vi.unstubAllGlobals()
  vi.spyOn(Date, 'now').mockReturnValue(NOW)
  vi.setSystemTime(NOW)
  installWindow()
})

describe('r75 笔试草稿', () => {
  it('写入读取往返，并按作答起点恢复连续计时', () => {
    const startedAt = new Date(NOW - 65_000).toISOString()
    expect(writeExamDraft('u1', { run: RUN, answers: { q1: ['A'], q2: ['B', 'C'] }, startedAt })).toBe(true)
    const read = readExamDraft('u1', NOW)
    expect(read.status).toBe('ok')
    if (read.status === 'ok') {
      expect(read.draft.run).toEqual(RUN)
      expect(read.draft.answers).toEqual({ q1: ['A'], q2: ['B', 'C'] })
      expect(read.elapsedS).toBe(65)
    }
  })

  it('按账号隔离，匿名用户不写', () => {
    expect(writeExamDraft(null, { run: RUN, answers: {}, startedAt: new Date(NOW).toISOString() })).toBe(false)
    expect(store.has(examDraftKey(null))).toBe(false)
    expect(readExamDraft(null, NOW)).toEqual({ status: 'none' })
    writeExamDraft('u1', { run: RUN, answers: {}, startedAt: new Date(NOW).toISOString() })
    expect(readExamDraft('u2', NOW)).toEqual({ status: 'none' })
  })

  it('超过 24 小时返回 expired，纯读不删除', () => {
    writeExamDraft('u1', { run: RUN, answers: { q1: ['A'] }, startedAt: new Date(NOW - 90_000_000).toISOString() })
    const key = examDraftKey('u1')
    const saved = JSON.parse(store.get(key)!) as { saved_at: string }
    store.set(key, JSON.stringify({ ...saved, saved_at: new Date(NOW - EXAM_DRAFT_TTL_MS - 1).toISOString() }))
    expect(readExamDraft('u1', NOW).status).toBe('expired')
    expect(readExamDraft('u1', NOW).status).toBe('expired')
    expect(store.has(key)).toBe(true)
  })

  it('损坏 JSON 与错误版本返回 invalid', () => {
    store.set(examDraftKey('u1'), '{bad')
    expect(readExamDraft('u1', NOW).status).toBe('invalid')
    store.set(examDraftKey('u1'), JSON.stringify({ version: 2 }))
    expect(readExamDraft('u1', NOW).status).toBe('invalid')
  })

  it('run_id 不一致或空卷返回 invalid', () => {
    store.set(examDraftKey('u1'), JSON.stringify({
      version: 1, run_id: 'other', run: RUN, answers: {}, started_at: new Date(NOW).toISOString(), saved_at: new Date(NOW).toISOString(),
    }))
    expect(readExamDraft('u1', NOW).status).toBe('invalid')
    store.set(examDraftKey('u1'), JSON.stringify({
      version: 1, run_id: RUN.run_id, run: { ...RUN, questions: [] }, answers: {}, started_at: new Date(NOW).toISOString(), saved_at: new Date(NOW).toISOString(),
    }))
    expect(readExamDraft('u1', NOW).status).toBe('invalid')
  })

  it('旧卷答案键或值不合法时整份拒绝', () => {
    writeExamDraft('u1', { run: RUN, answers: {}, startedAt: new Date(NOW).toISOString() })
    const key = examDraftKey('u1')
    const saved = JSON.parse(store.get(key)!) as object
    store.set(key, JSON.stringify({ ...saved, answers: { other: ['A'] } }))
    expect(readExamDraft('u1', NOW).status).toBe('invalid')
    store.set(key, JSON.stringify({ ...saved, answers: { q1: [1] } }))
    expect(readExamDraft('u1', NOW).status).toBe('invalid')
  })

  it('未来保存时间与非法起点均拒绝', () => {
    writeExamDraft('u1', { run: RUN, answers: {}, startedAt: new Date(NOW).toISOString() })
    const key = examDraftKey('u1')
    const saved = JSON.parse(store.get(key)!) as object
    store.set(key, JSON.stringify({ ...saved, saved_at: new Date(NOW + 10 * 60_000).toISOString() }))
    expect(readExamDraft('u1', NOW).status).toBe('invalid')
    store.set(key, JSON.stringify({ ...saved, started_at: 'bad' }))
    expect(readExamDraft('u1', NOW).status).toBe('invalid')
  })

  it('起点晚于当前时间时计时不为负', () => {
    writeExamDraft('u1', { run: RUN, answers: {}, startedAt: new Date(NOW + 60_000).toISOString() })
    const read = readExamDraft('u1', NOW)
    expect(read.status).toBe('ok')
    if (read.status === 'ok') expect(read.elapsedS).toBe(0)
  })

  it('清除后返回 none', () => {
    writeExamDraft('u1', { run: RUN, answers: {}, startedAt: new Date(NOW).toISOString() })
    clearExamDraft('u1')
    expect(readExamDraft('u1', NOW)).toEqual({ status: 'none' })
  })

  it('存储写失败返回 false，不抛出', () => {
    failWrite = true
    expect(writeExamDraft('u1', { run: RUN, answers: {}, startedAt: new Date(NOW).toISOString() })).toBe(false)
  })

  it('存储读失败按无草稿处理', () => {
    vi.stubGlobal('window', { localStorage: { getItem: () => { throw new Error('blocked') } } })
    expect(readExamDraft('u1', NOW)).toEqual({ status: 'none' })
  })

  it('清除存储失败也不抛出', () => {
    vi.stubGlobal('window', { localStorage: { removeItem: () => { throw new Error('blocked') } } })
    expect(() => clearExamDraft('u1')).not.toThrow()
  })
})
