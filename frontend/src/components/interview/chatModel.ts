/**
 * 对话流的**纯函数口径**（TECHNICAL §6.2）—— 组件文件只导出组件，纯函数集中到这里。
 *
 * 为什么单独成文件：`react-refresh/only-export-components` 要求「组件文件只导出组件」，
 * 否则任意一次热更新都会退化成整页重载（AC-15 的 lint 上限，QA D-3）。这里放的都是
 * 可被 vitest 在 node 环境直接测的纯函数，不含任何 React 依赖。
 */

import type { InterviewSessionQuestion, InterviewSettings } from '../../api/types'
import { scoreRingState } from './scoreModel'

/** 得分档位词的三档（与 ScoreBadge 的环形状态一一对应，不写第二套阈值）。 */
export type ScoreTier = 'good' | 'mid' | 'low'

/**
 * 档位唯一映射：直接复用 ScoreBadge 的 `scoreRingState`（>7 / ≥4 / 其余），
 * 不写第二套阈值（否则同一分在气泡与结束态会显示成两档）。
 */
export function scoreTier(score: number): ScoreTier {
  const state = scoreRingState(score)
  if (state === 'success') return 'good'
  if (state === 'warn') return 'mid'
  return 'low'
}

/**
 * 题号唯一入口（AC-8）：`iq-12` → 12；非该形态一律 0（表示「未编号」，不猜、不按顺序补号）。
 * 气泡（`ChatBubble`）、容器（`ChatStream`）与测试都只认这一份解析。
 */
export function questionNoOf(id: string): number {
  const match = /^iq-(\d+)$/.exec(id)
  return match ? Number(match[1]) : 0
}

/**
 * 气泡序列的一项。`question` 在两处都带上：
 * 面试官泡用它取题面/提示/题号，候选泡用它取「第 N 轮作答」的题号与追问标注。
 */
export interface Bubble {
  role: 'interviewer' | 'candidate'
  id: string
  question?: InterviewSessionQuestion
  answer?: string | null
  score?: number | null
  comment?: string | null
}

/** 候选泡 id 后缀：与面试官泡（题 id 本身）区分，保证 key 唯一。 */
const ANSWER_SUFFIX = ':a'

/**
 * 题目链 → 气泡序列（AC-4 的可判定口径）：每条已提出的题 = 1 条面试官泡；
 * 该题一旦有作答，其下紧跟 1 条候选人气泡（评分区在该泡内）。因此
 * 「面试官泡条数 == 已提出题数」，不按渲染顺序补号、不预铺未来题。
 */
export function bubblesOf(questions: InterviewSessionQuestion[]): Bubble[] {
  const bubbles: Bubble[] = []
  for (const question of questions) {
    bubbles.push({ role: 'interviewer', id: question.id, question })
    if (question.answer !== null) {
      bubbles.push({
        role: 'candidate',
        id: `${question.id}${ANSWER_SUFFIX}`,
        question,
        answer: question.answer,
        score: question.score,
        comment: question.comment,
      })
    }
  }
  return bubbles
}

/** 题型（结束态按类型给均分用）。 */
export type QuestionKind = InterviewSessionQuestion['kind']

/** 均分口径与后端 `history.score_of` 对齐：算术平均，展示层四舍五入由 `formatScore` 收口（保留 1 位）。 */
export function averageOf(values: number[]): number {
  if (values.length === 0) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

/** 分类均分：只统计已出分的同类型题；无样本时返回 0（页面据样本数决定是否显示「—」）。 */
export function kindAverageOf(questions: InterviewSessionQuestion[], kind: QuestionKind): number {
  const values = questions
    .filter((question) => question.kind === kind)
    .map((question) => question.score)
    .filter((score): score is number => typeof score === 'number')
  return averageOf(values)
}

/** 无设定（旧 run / 笔试 / 未记录）时的固定文案：绝不出现 undefined / 空行（AC-11）。 */
export const SETTINGS_UNKNOWN = '未记录设定'

/**
 * 本场设定的唯一格式化入口（AC-11 / TECHNICAL §4.2）。
 * 会话顶、报告顶、历史行三处都调它，避免各拼一份出现「未记录设定 / undefined」漂移。
 */
export function settingsLine(settings: InterviewSettings | null): string {
  if (!settings) return SETTINGS_UNKNOWN
  const parts = [
    settings.target_role,
    settings.years_experience,
    settings.market,
    settings.company_size,
  ].filter((part) => typeof part === 'string' && part.trim().length > 0)
  // 方向聚焦只在显式选了方向时追加（旧 run 没有这两键，文案保持四项不变）。
  const focus = [settings.direction, settings.sub_direction]
    .filter((part): part is string => typeof part === 'string' && part.trim().length > 0)
    .join(' · ')
  if (focus.length > 0) parts.push(focus)
  return parts.length > 0 ? parts.join(' · ') : SETTINGS_UNKNOWN
}
