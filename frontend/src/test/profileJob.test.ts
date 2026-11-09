import { describe, expect, it } from 'vitest'
import type { ProfileJobStatus } from '../api/types'
import {
  PROFILE_JOB_FAILURE_WINDOW_MS,
  PROFILE_JOB_POLL_MS,
  isJobRunning,
  jobElapsedSec,
  jobFailureNotice,
  jobToResumeMeta,
  shouldReattach,
  shouldSurfaceFailure,
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

  it('重接入的已用秒数从任务真实起点起算（r35）：时间不可解 / 未来时间戳按 0', () => {
    const now = Date.parse('2026-11-05T06:00:40+00:00')
    expect(jobElapsedSec(job({ created_at: '2026-11-05T06:00:00+00:00' }), now)).toBe(40)
    // 不足 1 秒向下取整；时间戳缺失或不可解时不猜，按 0。
    expect(jobElapsedSec(job({ created_at: '2026-11-05T06:00:39.9+00:00' }), now)).toBe(0)
    expect(jobElapsedSec(job({ created_at: '' }), now)).toBe(0)
    expect(jobElapsedSec(job({ created_at: 'not-a-date' }), now)).toBe(0)
    // 本机时钟偏慢（created_at 在未来）：不给负数。
    expect(jobElapsedSec(job({ created_at: '2026-11-05T06:01:00+00:00' }), now)).toBe(0)
  })

  it('jobToResumeMeta 用任务行补齐上传卡片信息（document_id 即 resume_id）', () => {
    const meta = jobToResumeMeta(job())
    expect(meta).toEqual({
      resume_id: 'res-1',
      file_name: '简历.pdf',
      chars: 1200,
      sections: 4,
      source_type: 'pdf',
      image_count: 1,
    })
  })

  it('最近一次任务是 failed 时必须在上传页明示（r32）：completed/running 不明示', () => {
    const now = Date.parse('2026-11-05T08:00:00+00:00')
    expect(shouldSurfaceFailure(job({ status: 'failed' }), now)).toBe(true)
    expect(shouldSurfaceFailure(job({ status: 'running' }), now)).toBe(false)
    expect(shouldSurfaceFailure(job({ status: 'completed' }), now)).toBe(false)
  })

  it('失败提示带 24 小时时效（r33）：过期旧失败不常驻，时间不可解时仍展示', () => {
    const created = '2026-11-05T08:00:00+00:00'
    const createdMs = Date.parse(created)
    const failed = job({ status: 'failed', created_at: created })

    // 窗口内（含边界）展示，窗口外不打扰。
    expect(shouldSurfaceFailure(failed, createdMs + PROFILE_JOB_FAILURE_WINDOW_MS)).toBe(true)
    expect(shouldSurfaceFailure(failed, createdMs + PROFILE_JOB_FAILURE_WINDOW_MS + 1)).toBe(
      false,
    )
    // 时间戳缺失/不可解：宁可展示也不静默。
    expect(shouldSurfaceFailure(job({ status: 'failed', created_at: '' }))).toBe(true)
    expect(shouldSurfaceFailure(job({ status: 'failed', created_at: 'not-a-date' }))).toBe(true)
  })

  it('失败文案：先说明上传已完成，再给后端中文原因（缺省给通用提示）', () => {
    expect(jobFailureNotice(job({ error: '简历正文无法用于生成画像' }))).toBe(
      '简历已上传成功，但画像生成失败：简历正文无法用于生成画像',
    )
    expect(jobFailureNotice(job({ error: '' }))).toBe('简历已上传成功，但画像生成失败，请稍后重试')
    expect(jobFailureNotice(job({ error: '   ' }))).toBe(
      '简历已上传成功，但画像生成失败，请稍后重试',
    )
  })
})
