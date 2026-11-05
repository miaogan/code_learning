import type { ProfileJobStatus, ResumeMeta } from '../api/types'

/**
 * r30 异步画像任务的纯逻辑（UploadPage 轮询 / 重接入共用， vitest 覆盖）。
 *
 * 后台任务语义：受理后前端只凭 `job_id` 轮询，生成期间用户可以随便离开 ——
 * 回到上传页时用 `latestProfileJob` 把还在跑的任务接上。
 */

/** 轮询间隔：画像生成 20~60 秒量级，2 秒跟手且不给后端压力。 */
export const PROFILE_JOB_POLL_MS = 2000

/** 任务是否仍在后台跑（前端要继续轮询）。 */
export function isJobRunning(job: Pick<ProfileJobStatus, 'status'>): boolean {
  return job.status === 'running'
}

/**
 * 是否值得「接上」：只有 running 的任务需要接管进度；
 * completed / failed 的历史任务一律走「已有画像」读路径（`GET /api/profiles/latest`），不重放旧卡片。
 */
export function shouldReattach(job: Pick<ProfileJobStatus, 'status'>): boolean {
  return job.status === 'running'
}

/** 任务行 → 上传页卡片用的 ResumeMeta（接上后台任务时，文件信息全部来自任务行，不依赖本页状态）。 */
export function jobToResumeMeta(job: ProfileJobStatus): ResumeMeta {
  return {
    resume_id: job.document_id,
    file_name: job.file_name,
    chars: job.chars,
    sections: job.sections,
  }
}

/** 失败任务的展示文案：后端已落中文原因，缺省时给通用提示（不猜技术细节）。 */
export function jobFailureMessage(job: Pick<ProfileJobStatus, 'error'>): string {
  return job.error.trim() || '画像生成失败，请稍后重试'
}
