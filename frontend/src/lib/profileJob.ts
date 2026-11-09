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

/**
 * 最近一次任务失败时是否要在上传页明示（r32）：只要最近一次尝试是 failed 就如实展示——
 * 用户离开后任务在后台失败、回来页面上却毫无痕迹，正是「上传失败却没报错」的主因。
 *
 * r33：加时效窗口 —— 过了 24 小时的旧失败不再常驻提示（否则一条历史失败会挂在每次打开，
 * 用户看到「接口全 200 却总说失败」）。真正的失败都在 24h 内可见；之后 latest 若仍是 failed，
 * 也说明用户早已不再等这一次结果，不再打扰。
 */
export const PROFILE_JOB_FAILURE_WINDOW_MS = 24 * 60 * 60 * 1000

export function shouldSurfaceFailure(
  job: Pick<ProfileJobStatus, 'status'> & Partial<Pick<ProfileJobStatus, 'created_at'>>,
  nowMs: number = Date.now(),
): boolean {
  if (job.status !== 'failed') return false
  // 时间拿不到时宁可展示（可见性优先）：解析不出时刻不代表失败不该被看到。
  const createdMs = job.created_at ? Date.parse(job.created_at) : Number.NaN
  if (Number.isNaN(createdMs)) return true
  return nowMs - createdMs <= PROFILE_JOB_FAILURE_WINDOW_MS
}

/** 任务行 → 上传页卡片用的 ResumeMeta（接上后台任务时，文件信息全部来自任务行，不依赖本页状态）。 */
export function jobToResumeMeta(job: ProfileJobStatus): ResumeMeta {
  return {
    resume_id: job.document_id,
    file_name: job.file_name,
    chars: job.chars,
    sections: job.sections,
    // 任务行只记文档名与字数（r41 未扩表）：重接入只用于展示文件名与续跑，
    // 图片来源信息只在「本次上传」的响应里用得到。
    source_type: 'pdf',
    image_count: 1,
  }
}

/**
 * 重接入时的「已用秒数」（r35）：任务行带 `created_at`，接上进度时秒数应从真实起点起算 ——
 * 之前重接入后从 0 开始计，任务明明跑了 40 秒，页面上显示「已用 1s」，进度语义失真。
 * 时间不可解时按 0（宁少勿错），未来时间戳（本机时钟偏差）按 0。
 */
export function jobElapsedSec(
  job: Pick<ProfileJobStatus, 'created_at'>,
  nowMs: number = Date.now(),
): number {
  const createdMs = Date.parse(job.created_at)
  if (Number.isNaN(createdMs)) return 0
  return Math.max(0, Math.floor((nowMs - createdMs) / 1000))
}

/**
 * 上传页错误条文案（r33）：异步任务接口恒为 200，失败只体现在 body.status ——
 * 文案要先把「上传/解析已完成」说清，再给生成失败原因，避免用户误以为上传接口挂了。
 */
export function jobFailureNotice(job: Pick<ProfileJobStatus, 'error'>): string {
  const reason = job.error.trim()
  return reason
    ? `简历已上传成功，但画像生成失败：${reason}`
    : '简历已上传成功，但画像生成失败，请稍后重试'
}
