/**
 * r77 太傅对话的纯函数层：问句清洗、发送闸门、段落切分、引用去重。
 *
 * 放在这里而不是组件里，是为了让「超长问句」「连续空行」这类边界可单测，
 * 组件只管状态与渲染。服务端同样会做一次截断（`policy.sanitize_question`），
 * 前端这一份是**为了即时反馈**，不是为了替代服务端校验。
 */

import type { TaifuCitation } from '../api/types'

/** 与服务端 `policy.QUESTION_MAX` 对齐：超过这个长度的一句话基本已不是「问题」。 */
export const TAIFU_QUESTION_MAX = 200

/** 首屏示例问题：点击填入输入框，不自动发送（用户可能想改一改再问）。 */
export const TAIFU_SAMPLES: string[] = [
  '我最近一次测评为什么掉分？',
  '按我现在的短板，本周先做什么？',
  '我的项目怎么讲成面试官能追问的证据？',
]

/** 压平空白 + 截断：换行会破坏「一句话问题」的形态，统一压成单空格。 */
export function clampQuestion(raw: string): string {
  const flat = raw.replace(/\s+/g, ' ').trim()
  if (flat.length <= TAIFU_QUESTION_MAX) return flat
  return `${flat.slice(0, TAIFU_QUESTION_MAX).trimEnd()}…`
}

/** 发送闸门：空问句不发，请求在途时不重复发。 */
export function canSend(question: string, pending: boolean): boolean {
  return !pending && clampQuestion(question).length > 0
}

/** 回答按段落渲染：连续换行不产生空段落，首尾空白不计。 */
export function paragraphsOf(text: string): string[] {
  return text
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

/** 引用去重（按 href 保序）：服务端已去重，这一层防「本地拼接出重复链接」。 */
export function uniqueCitations(citations: TaifuCitation[]): TaifuCitation[] {
  const seen = new Set<string>()
  const kept: TaifuCitation[] = []
  citations.forEach((citation) => {
    const href = citation.href.trim()
    if (!href || seen.has(href)) return
    seen.add(href)
    kept.push({ label: citation.label || href, href })
  })
  return kept
}
