/**
 * r131 镜试缺项回灌修文：纯函数层（页面零判断）。
 *
 * 口径：
 * 1. 缺失信息来自镜试复盘卡（AI 只说缺什么、不代填），此处只做**收集、去重与排序**，
 *    不改写、不拆句——改写会破坏「候选人亲口补充」的事实边界；
 * 2. 去重按整条文本精确相等（跨卡重复的缺项只保留第一条，但记录提及次数）；
 * 3. 排序是**本地确定性规则**，不引入 AI 判定、不改契约：跨卡重复提及次数 + 内容对
 *    简历竞争力的影响（量化结果 > 业务影响 > 责任/落地 > 技术细节 > 泛泛补充）；
 * 4. 跳转高亮（镜试 → 修文）走 navigation state，读取处必须容忍任意 history state。
 */

import type { PolishSection } from '../api/types'

export type FactImportance = 'high' | 'medium' | 'low'

/** 一条待补写的镜试缺项（来源卡仅用于展示「来自哪次复盘」，不参与事实校验）。 */
export interface MirrorFactItem {
  text: string
  sourceCardId: string
  /** 最近 N 张复盘卡里被提及几次（>=1）；重复出现是客观的重要性信号。 */
  occurrences: number
  /** 本地排序分数，只用于 UI 排序与调试，不写回契约。 */
  score: number
  importance: FactImportance
}

interface MirrorCardLike {
  id: string
  missing_info: string[]
}

/* 内容权重：按「对简历竞争力的影响」分档，命中多档时取最高档，避免关键词堆砌刷分。 */
const VAGUE_RE = /补充一下|补充更多|详细描述|具体说明|更多细节|介绍一下|展开说说|展开描述/
const MEASURE_RE =
  /(?:\d+(?:\.\d+)?\s*(?:%|％|倍|万|亿|千|qps|tps|ms|秒|分钟|小时|天|人|台|节点|条|行|gb|tb|pv|uv))|(?:qps|tps|并发|吞吐|延迟|耗时|可用性|成功率|转化率|留存|增长|提升|下降|降低|成本|节省|容量|规模|数据量|性能指标)/i
const IMPACT_RE = /业务|收益|效果|结果|价值|影响|故障|事故|稳定性|效率|体验|营收|收入|转化|留存|风险/
const OWNERSHIP_RE = /主导|负责|独立|牵头|架构|设计|方案|推动|落地|上线|优化|治理|从零|搭建|迁移|重构|排障|定位|解决/
const TECH_RE =
  /源码|原理|调优|内核|机制|选型|对比|实现|技术栈|框架|组件|中间件|数据库|缓存|消息队列|分布式|微服务|容器|k8s|docker|redis|mysql|kafka|sql|索引|事务|锁|线程|进程|网络|io/i

function contentScore(text: string): number {
  if (MEASURE_RE.test(text)) return IMPACT_RE.test(text) ? 46 : 40
  if (IMPACT_RE.test(text)) return 34
  if (OWNERSHIP_RE.test(text)) return 26
  if (TECH_RE.test(text)) return 18
  if (VAGUE_RE.test(text)) return 4
  return 10
}

function importanceOf(score: number): FactImportance {
  if (score >= 40) return 'high'
  if (score >= 20) return 'medium'
  return 'low'
}

/** 收集全部复盘卡的缺失信息：拍平 + 按整条文本去重，累计提及次数并算本地重要性分。 */
export function collectMissingFacts(cards: MirrorCardLike[]): MirrorFactItem[] {
  const seen = new Map<string, MirrorFactItem>()
  const items: MirrorFactItem[] = []
  for (const card of cards) {
    for (const raw of card.missing_info) {
      const text = String(raw ?? '').trim()
      if (text === '') continue
      const existing = seen.get(text)
      if (existing !== undefined) {
        existing.occurrences += 1
        continue
      }
      const item: MirrorFactItem = {
        text,
        sourceCardId: card.id,
        occurrences: 1,
        score: 0,
        importance: 'low',
      }
      seen.set(text, item)
      items.push(item)
    }
  }
  return items.map((item) => {
    const score = contentScore(item.text) + Math.min((item.occurrences - 1) * 12, 36)
    return { ...item, score, importance: importanceOf(score) }
  })
}

/**
 * 按重要性从高到低排序列表：分数优先，其次提及次数，最后保持原首次出现顺序。
 * 只排序不改文本——「候选人亲口补充」的事实边界不能被动过。
 */
export function rankMissingFactsByImportance(items: MirrorFactItem[]): MirrorFactItem[] {
  const firstSeen = new Map(items.map((item, index) => [item.text, index]))
  return [...items].sort(
    (a, b) =>
      b.score - a.score ||
      b.occurrences - a.occurrences ||
      (firstSeen.get(a.text) ?? 0) - (firstSeen.get(b.text) ?? 0),
  )
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
