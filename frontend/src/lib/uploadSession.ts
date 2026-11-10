import type { ResumeMeta } from '../api/types'

/**
 * r42 上传会话（断连恢复的本地锚点）。
 *
 * 服务端任务本身就是真源，但「这个任务是不是我这次上传的」只有本机知道：
 * 手机上切 App / 锁屏 / 系统回收页面后回来，先读这个本地会话，能立刻接上在途任务，
 * 而不是从空白页重新开始。跨设备场景仍由服务端 `latest` 兜底。
 *
 * 存储按账号隔离（`sc.upload.<userId>`），24 小时后自动失效 —— 避免一次旧上传
 * 在很久以后回放，把「回访上传页」变成「卡在旧结果页」。
 */

export interface UploadSession {
  version: 1
  /** 本次上传走的入口：文档解析（同步）还是图片识别（后台任务）。 */
  source: 'file' | 'image'
  /** 图片识别任务 id（仅 source=image 且任务还在时存在）。 */
  resume_job_id?: string
  /** 画像生成任务 id（解析完成后受理）。 */
  profile_job_id?: string
  /** 解析完成的简历元信息（识别中可能还没有）。 */
  meta?: ResumeMeta
  saved_at: string
}

/** 本地会话有效期：跨过「锁屏一晚」但不过度久远。 */
export const UPLOAD_SESSION_TTL_MS = 24 * 60 * 60 * 1000

/** 已完成结果回放窗口：短时间内重进页面能看到「刚才那次完成」，久远的完成不打扰。 */
export const COMPLETED_REPLAY_WINDOW_MS = 30 * 60 * 1000

const KEY_PREFIX = 'sc.upload'

export function uploadSessionKey(userId: string | null): string {
  return `${KEY_PREFIX}.${userId ?? 'anon'}`
}

function safeGetItem(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSetItem(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* 隐私模式 / 配额满：会话恢复尽力而为，不影响上传主流程 */
  }
}

function safeRemoveItem(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    /* 同上 */
  }
}

function parseSession(raw: string): UploadSession | null {
  try {
    const parsed = JSON.parse(raw) as Partial<UploadSession> | null
    if (parsed === null || typeof parsed !== 'object') return null
    if (parsed.version !== 1) return null
    if (parsed.source !== 'file' && parsed.source !== 'image') return null
    if (typeof parsed.saved_at !== 'string' || Number.isNaN(Date.parse(parsed.saved_at))) {
      return null
    }
    if (parsed.resume_job_id !== undefined && typeof parsed.resume_job_id !== 'string') return null
    if (parsed.profile_job_id !== undefined && typeof parsed.profile_job_id !== 'string') return null
    return parsed as UploadSession
  } catch {
    return null
  }
}

/** 读取本账号的上传会话；过期 / 结构不合法一律返回 null（并顺手清掉脏数据）。 */
export function readUploadSession(
  userId: string | null,
  nowMs: number = Date.now(),
): UploadSession | null {
  const key = uploadSessionKey(userId)
  const raw = safeGetItem(key)
  if (raw === null) return null
  const session = parseSession(raw)
  if (session === null) {
    safeRemoveItem(key)
    return null
  }
  const savedMs = Date.parse(session.saved_at)
  if (nowMs - savedMs > UPLOAD_SESSION_TTL_MS) {
    safeRemoveItem(key)
    return null
  }
  return session
}

/**
 * 写会话。`userId` 为空（登录态未就绪 / 已登出）时**不写**：否则会落到 `sc.upload.anon`
 * 这个跨账号共享的键上 —— 恢复时按真实 userId 读不到，而且会变成别人也能读到的脏数据。
 */
export function writeUploadSession(
  userId: string | null,
  session: Omit<UploadSession, 'version' | 'saved_at'>,
): UploadSession | null {
  if (userId === null) return null
  const next: UploadSession = { ...session, version: 1, saved_at: new Date().toISOString() }
  safeSetItem(uploadSessionKey(userId), JSON.stringify(next))
  return next
}

export function clearUploadSession(userId: string | null): void {
  safeRemoveItem(uploadSessionKey(userId))
}

/**
 * 已完成任务是否值得回放：只有「刚完成」的才展示结果卡片；
 * 更早的完成说明用户早就走远了，回到正常「已有画像」读路径即可。
 */
export function shouldReplayCompleted(
  createdAt: string,
  nowMs: number = Date.now(),
): boolean {
  const createdMs = Date.parse(createdAt)
  if (Number.isNaN(createdMs)) return false
  return nowMs - createdMs <= COMPLETED_REPLAY_WINDOW_MS
}

/** 任务已用秒数（与 r35 同口径：从任务行 `created_at` 起算，时间不可解按 0）。 */
export function elapsedSince(createdAt: string, nowMs: number = Date.now()): number {
  const createdMs = Date.parse(createdAt)
  if (Number.isNaN(createdMs)) return 0
  return Math.max(0, Math.floor((nowMs - createdMs) / 1000))
}

// --- HEIC（iPhone 默认格式）---------------------------------------------------

/** HEIF / HEIC 家族品牌：`ftyp` 的 major brand 与兼容品牌都可能是其中任意一个。 */
const HEIF_BRANDS = new Set(['heic', 'heix', 'hevc', 'hevx', 'heim', 'heis', 'mif1', 'msf1'])

/** HEIC 解码失败时给用户的中文替代路径（相机格式改成「兼容性最佳」或导出 JPG）。 */
export const HEIC_UNSUPPORTED_HINT =
  '这是 iPhone 的 HEIC 照片，当前浏览器无法直接处理。' +
  '请在「设置 → 相机 → 格式」里选择「兼容性最佳」后重新拍摄，' +
  '或在相册里导出为 JPG / PNG 再上传。'

/** 只读文件头 32 字节即可判定：`ftyp` 盒在偏移 4，major brand 在偏移 8。 */
export const HEIC_SNIFF_BYTES = 32

/** 纯函数：按真实字节判断 HEIC / HEIF（不看扩展名与 MIME）。 */
export function isHeifHeader(head: Uint8Array): boolean {
  if (head.length < 12) return false
  const tag = String.fromCharCode(head[4], head[5], head[6], head[7])
  if (tag !== 'ftyp') return false
  const brand = String.fromCharCode(head[8], head[9], head[10], head[11])
  if (HEIF_BRANDS.has(brand)) return true
  const boxSize = (head[0] << 24) | (head[1] << 16) | (head[2] << 8) | head[3]
  const end = Math.min(head.length, boxSize > 0 ? boxSize : head.length)
  for (let offset = 16; offset + 4 <= end; offset += 4) {
    const compatible = String.fromCharCode(
      head[offset],
      head[offset + 1],
      head[offset + 2],
      head[offset + 3],
    )
    if (HEIF_BRANDS.has(compatible)) return true
  }
  return false
}

/** 读取文件头并判断是否 HEIC（读失败按「不是 HEIC」处理，交给后面的解码环节报错）。 */
export async function isHeifFile(file: File): Promise<boolean> {
  try {
    const head = new Uint8Array(await file.slice(0, HEIC_SNIFF_BYTES).arrayBuffer())
    return isHeifHeader(head)
  } catch {
    return false
  }
}
