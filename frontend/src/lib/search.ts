/**
 * 全站检索（r64）的展示层纯函数：输入归一化、可检索判定、命中项跳转、题面预览。
 *
 * 检索能力本身早已存在 —— 教程侧是 `tutorialSearch.ts` 的 BM25 纯函数，
 * 题库侧是 `POST /api/search/questions`（FTS5 优先，服务端可降级到模糊匹配）。
 * 这里只补「页面零计算」需要的那点映射，**不改任何检索口径**。
 */
import { practiceHref } from './studyPlan'

/** 教程一次最多展示多少条小节命中（BM25 已排序，取前 N）。 */
export const TUTORIAL_HIT_LIMIT = 8
/** 题库一次请求多少条（与后端 limit 上限一致）。 */
export const QUESTION_HIT_LIMIT = 10
/** 题库检索是网络请求：停止输入 300ms 后才查；教程侧是纯函数，输入即出结果。 */
export const QUESTION_DEBOUNCE_MS = 300

/** 归一化输入：全角空格转半角、连续空白压成一个空格、去掉首尾空白。 */
export function normalizeQuery(raw: string): string {
  return raw.replace(/\u3000/g, ' ').replace(/\s+/g, ' ').trim()
}

/** 至少有一个字母 / 数字 / 汉字才发起检索：纯标点与空格不查（否则会命中过宽的文档集）。 */
export function isSearchable(query: string): boolean {
  return /[A-Za-z0-9\u3400-\u9fff]/.test(query)
}

/** 题库命中 → 练习页：题目没有独立详情页，按命中题的方向 / 子方向带到练习筛选。 */
export function questionHref(item: { direction: string; sub_direction: string }): string {
  const direction = item.direction.trim()
  return practiceHref({
    direction: direction === '' ? null : direction,
    sub_direction: item.sub_direction,
  })
}

/** 题面预览：压平换行与连续空白（题面常含代码与表格），超长截断并加省略号。 */
export function previewText(text: string, max = 120): string {
  const flat = normalizeQuery(text)
  if (max <= 0) return ''
  return flat.length <= max ? flat : `${flat.slice(0, max)}…`
}
