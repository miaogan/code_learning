/**
 * 播放器的纯逻辑层（r151）：倍速档位、时间格式化、句级定位、断点有效性守卫。
 *
 * 抽出来的原因与 `learnProgress.ts` 相同：播放器组件要快进快出，
 * 这些逻辑要在 vitest（node 环境、无 `<audio>`）里单测锁死。
 * 断点的**存取**走 `state/learnProgress`（本地缓存 + 服务端契约同步），
 * 本文件只负责「这条断点还有效吗」的判定。
 */
import type { SpokenAudioCue } from './spokenAudio'

/** 倍速档位（VERSION-PLAN §4.1：0.75–2.0）。顺序即 UI 顺序。 */
export const PLAYBACK_SPEEDS = [0.75, 1, 1.25, 1.5, 2] as const

/** `m:ss`：进度条两端的口径，负数与 NaN 一律归零显示 0:00。 */
export function formatMs(ms: number): string {
  const total = Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : 0
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

/**
 * 位置 → 正在播的句下标：`startMs <= position < endMs`；
 * 停顿间隙（两句之间）返回上一句（高亮停留在刚说完的句，符合听感）；
 * 越界（开头前 / 结尾后）返回 0 / 末句，绝不返回 -1 让渲染层崩。
 */
export function activeCueIndex(cues: readonly SpokenAudioCue[], positionMs: number): number {
  if (cues.length === 0) return 0
  if (positionMs < cues[0].startMs) return 0
  for (let i = cues.length - 1; i >= 0; i -= 1) {
    if (positionMs >= cues[i].startMs) return i
  }
  return 0
}

/** 断点续听的一条记录：节 id + 节内毫秒位置。 */
export interface ListenResume {
  sectionId: string
  positionMs: number
}

/** 断点续听的位置上限守卫：位置必须落在节时长内，否则视为无效（章节改版 / 换音频）。 */
export function validResume(
  resume: ListenResume | null,
  sectionIds: readonly string[],
  durationMs: number | undefined,
): ListenResume | null {
  if (resume === null) return null
  if (!sectionIds.includes(resume.sectionId)) return null
  if (!Number.isFinite(resume.positionMs) || resume.positionMs <= 0) return null
  if (durationMs !== undefined && resume.positionMs >= durationMs) return null
  return resume
}
