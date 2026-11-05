import { describe, expect, it } from 'vitest'
import type { ProfileJobStatus } from '../api/types'
import {
  PROFILE_JOB_POLL_MS,
  isJobRunning,
  jobFailureMessage,
  jobToResumeMeta,
  shouldReattach,
} from '../lib/profileJob'

function job(overrides: Partial<ProfileJobStatus> = {}): ProfileJobStatus {
  return {
    job_id: 'job-1',
    document_id: 'res-1',
    file_name: '简历.pdf',
    chars: 1200,
    sections: 4,
    status: 'running',
    error: '',
    result: null,
    created_at: '2026-11-05T06:00:00+00:00',
    ...overrides,
  }
}

describe('profileJob 轮询语义', () => {
  it('轮询间隔固定 2 秒', () => {
    expect(PROFILE_JOB_POLL_MS).toBe(2000)
  })

  it('只有 running 需要继续轮询 / 接上，终态都不需要', () => {
    expect(isJobRunning(job({ status: 'running' }))).toBe(true)
    expect(isJobRunning(job({ status: 'completed' }))).toBe(false)
    expect(isJobRunning(job({ status: 'failed' }))).toBe(false)

    expect(shouldReattach(job({ status: 'running' }))).toBe(true)
    // 历史终态任务不重放旧卡片：completed 走「已有画像」读路径。
    expect(shouldReattach(job({ status: 'completed' }))).toBe(false)
    expect(shouldReattach(job({ status: 'failed' }))).toBe(false)
  })

  it('jobToResumeMeta 用任务行补齐上传卡片信息（document_id 即 resume_id）', () => {
    const meta = jobToResumeMeta(job())
    expect(meta).toEqual({
      resume_id: 'res-1',
      file_name: '简历.pdf',
      chars: 1200,
      sections: 4,
    })
  })

  it('失败文案：后端中文原因优先，缺省给通用提示', () => {
    expect(jobFailureMessage(job({ error: '简历正文无法用于生成画像' }))).toBe(
      '简历正文无法用于生成画像',
    )
    expect(jobFailureMessage(job({ error: '' }))).toBe('画像生成失败，请稍后重试')
    expect(jobFailureMessage(job({ error: '   ' }))).toBe('画像生成失败，请稍后重试')
  })
})
