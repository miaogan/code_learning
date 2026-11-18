/**
 * r131 镜试缺项回灌修文：纯函数层（页面零判断）。
 *
 * 口径：
 * 1. 缺失信息来自镜试复盘卡（AI 只说缺什么、不代填），此处只做**收集与去重**，
 *    不改写、不拆句——改写会破坏「候选人亲口补充」的事实边界；
 * 2. 去重按整条文本精确相等（跨卡重复的缺项只保留第一条）；
 * 3. 跳转高亮（镜试 → 修文）走 navigation state，读取处必须容忍任意 history state。
 */

import type { PolishSection } from '../api/types'

/** 一条待补写的镜试缺项（来源卡仅用于展示「来自哪次复盘」，不参与事实校验）。 */
export interface MirrorFactItem {
  text: string
  sourceCardId: string
}

interface MirrorCardLike {
  id: string
  missing_info: string[]
}

/** 收集全部复盘卡的缺失信息：拍平 + 按整条文本去重（保持首次出现顺序）。 */
export function collectMissingFacts(cards: MirrorCardLike[]): MirrorFactItem[] {
  const seen = new Set<string>()
  const items: MirrorFactItem[] = []
  for (const card of cards) {
    for (const raw of card.missing_info) {
      const text = String(raw ?? '').trim()
      if (text === '' || seen.has(text)) continue
      seen.add(text)
      items.push({ text, sourceCardId: card.id })
    }
  }
  return items
}

/** 镜试页「去修文补写」跳转时带的 state：只认字符串，其余一律忽略。 */
export function mirrorMissingFromState(state: unknown): string | null {
  if (typeof state !== 'object' || state === null) return null
  const raw = (state as { mirrorMissing?: unknown }).mirrorMissing
  if (typeof raw !== 'string') return null
  const text = raw.trim()
  return text === '' ? null : text
}

/** r131 回灌载荷：把补写内容转成契约 `user_facts`；空串跳过（防御，UI 已拦）。 */
export function toUserFacts(
  entries: { text: string; section: PolishSection | null }[],
): { text: string; section: PolishSection | null }[] {
  return entries
    .map((entry) => ({ text: entry.text.trim(), section: entry.section }))
    .filter((entry) => entry.text.length >= 2)
}
