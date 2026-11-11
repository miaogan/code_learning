import { describe, expect, it } from 'vitest'
import type { InterviewSessionQuestion, InterviewSettings, RunSummary } from '../api/types'
import {
  SETTINGS_UNKNOWN,
  averageOf,
  bubblesOf,
  kindAverageOf,
  questionNoOf,
  scoreTier,
  settingsLine,
} from '../components/interview/chatModel'
import { settingsTextOf } from '../components/history/trendModel'
import { formatScore } from '../lib/format'

/**
 * 对话流与回溯文本的纯函数口径（TECHNICAL §6.2）。
 * 渲染细节（粘性输入区、滚动锚点）不在 node 环境里测；这里钉住「题号 / 气泡序列 /
 * 档位边界 / 均分 / 点评逐字 / 设定文本三态」这些能复算的东西。
 */

function question(
  id: string,
  patch: Partial<InterviewSessionQuestion> = {},
): InterviewSessionQuestion {
  return {
    id,
    kind: 'technical',
    prompt: `${id} 的题面`,
    hint: '结合具体经历，说明做法、取舍与结果',
    parent_id: null,
    answer: null,
    score: null,
    comment: null,
    ...patch,
  }
}

const SETTINGS: InterviewSettings = {
  target_role: '后端工程师',
  years_experience: '3-5年',
  market: '北美',
  company_size: '初创',
}

function runSummary(patch: Partial<Omit<RunSummary, 'prev_score' | 'has_prev'>>): RunSummary {
  return {
    id: 'run-1',
    kind: 'interview',
    score: 6,
    shortfall_count: null,
    created_at: '2026-11-01T02:00:00+00:00',
    interview_settings: SETTINGS,
    prev_score: null,
    has_prev: false,
    ...patch,
  }
}

describe('questionNoOf：题号唯一入口（AC-8）', () => {
  it('iq-N 解析为 N，跨页复用同一编号', () => {
    expect(questionNoOf('iq-1')).toBe(1)
    expect(questionNoOf('iq-12')).toBe(12)
  })

  it('非 iq-N 形态一律 0（不按顺序补号、不猜）', () => {
    expect(questionNoOf('abc')).toBe(0)
    expect(questionNoOf('iq-')).toBe(0)
    expect(questionNoOf('iq-x')).toBe(0)
    expect(questionNoOf('IQ-1')).toBe(0)
    expect(questionNoOf('iq-1:a')).toBe(0)
  })
})

describe('bubblesOf：题目链 → 气泡序列（AC-4）', () => {
  it('n 题、m 已答 → n+m 条；面试官泡条数等于已提出题数', () => {
    const questions = [
      question('iq-1', { answer: '答一', score: 8, comment: '结构清楚' }),
      question('iq-2', { answer: '答二', score: 6, comment: '缺少量化' }),
      question('iq-3'),
    ]

    const bubbles = bubblesOf(questions)

    expect(bubbles.map((bubble) => `${bubble.role}:${bubble.id}`)).toEqual([
      'interviewer:iq-1',
      'candidate:iq-1:a',
      'interviewer:iq-2',
      'candidate:iq-2:a',
      'interviewer:iq-3',
    ])
    expect(bubbles.filter((bubble) => bubble.role === 'interviewer')).toHaveLength(
      questions.length,
    )
    expect(bubbles).toHaveLength(2 * questions.length - 1)
  })

  it('候选泡沿用同一条题目对象，评分与点评随泡携带（不预铺未来题）', () => {
    const answered = question('iq-1', { answer: '答一', score: 8.5, comment: '先理由再可改点' })

    const bubbles = bubblesOf([answered])

    expect(bubbles).toHaveLength(2)
    expect(bubbles[0].role).toBe('interviewer')
    expect(bubbles[0].question).toBe(answered)
    expect(bubbles[1].role).toBe('candidate')
    expect(bubbles[1].question).toBe(answered)
    expect(bubbles[1].answer).toBe('答一')
    expect(bubbles[1].score).toBe(8.5)
    expect(bubbles[1].comment).toBe('先理由再可改点')
  })

  it('空链 → 空序列；未答题只有面试官泡', () => {
    expect(bubblesOf([])).toEqual([])
    expect(bubblesOf([question('iq-1')])).toHaveLength(1)
  })

  it('追问气泡可反查父题编号（AC-6 的「↳ 追问自 Q2」依据）', () => {
    const bubbles = bubblesOf([question('iq-2', { parent_id: 'iq-1' })])

    expect(bubbles[0].question?.parent_id).toBe('iq-1')
    expect(questionNoOf(bubbles[0].question?.parent_id ?? '')).toBe(1)
  })
})

describe('scoreTier：档位边界与 ScoreBadge 同源（DESIGN §5 色盲可读）', () => {
  it.each([
    [0, 'low'],
    [3.9, 'low'],
    [4, 'mid'],
    [6, 'mid'],
    [7, 'mid'],
    [7.1, 'good'],
    [10, 'good'],
  ] as const)('%s 分 → %s', (score, tier) => {
    expect(scoreTier(score)).toBe(tier)
  })
})

describe('averageOf / kindAverageOf：均分口径（与后端 history.score_of 对齐）', () => {
  it('空集为 0（页面据样本数显示「—」而不是 0.0）', () => {
    expect(averageOf([])).toBe(0)
    expect(kindAverageOf([], 'technical')).toBe(0)
  })

  it('算术平均，展示层四舍五入交给 formatScore（一位小数）', () => {
    expect(averageOf([6, 8])).toBe(7)
    expect(averageOf([6, 7])).toBe(6.5)
    expect(formatScore(averageOf([7.2, 7.4]))).toBe('7.3')
  })

  it('分类均分只统计已出分的同类型题', () => {
    const questions = [
      question('iq-1', { kind: 'technical', answer: '答一', score: 8 }),
      question('iq-2', { kind: 'technical', answer: '答二', score: 6 }),
      question('iq-3', { kind: 'project', answer: '答三', score: 4 }),
      question('iq-4', { kind: 'project' }),
      question('iq-5', { kind: 'challenge' }),
    ]

    expect(kindAverageOf(questions, 'technical')).toBe(7)
    expect(kindAverageOf(questions, 'project')).toBe(4)
    expect(kindAverageOf(questions, 'challenge')).toBe(0)
  })
})

describe('settingsLine：本场设定唯一格式化入口（AC-11）', () => {
  it('四项以「·」连接，空值不产生空段', () => {
    expect(settingsLine(SETTINGS)).toBe('后端工程师 · 3-5年 · 北美 · 初创')
    expect(settingsLine({ ...SETTINGS, target_role: '   ' })).toBe('3-5年 · 北美 · 初创')
  })

  it('无设定 → 固定「未记录设定」，绝不出现 undefined / 空行', () => {
    expect(settingsLine(null)).toBe(SETTINGS_UNKNOWN)
    expect(SETTINGS_UNKNOWN).toBe('未记录设定')
  })
})

describe('settingsTextOf：历史行设定文本三态（AC-11）', () => {
  it('面试行有设定 → 同一格式化入口的文本', () => {
    expect(settingsTextOf(runSummary({}))).toBe('后端工程师 · 3-5年 · 北美 · 初创')
  })

  it('面试行无设定（旧 run）→ 未记录设定，不伪造默认值', () => {
    expect(settingsTextOf(runSummary({ interview_settings: null }))).toBe(SETTINGS_UNKNOWN)
  })

  it('笔试行没有「本场设定」概念 → null（整行不渲染）', () => {
    expect(settingsTextOf(runSummary({ kind: 'exam', interview_settings: null }))).toBeNull()
  })
})

describe('点评逐字渲染：零 trim / 零截断 / 零裁剪', () => {
  it('首尾空格与换行原样进气泡（数据层不再加工）', () => {
    const raw = '  先讲理由：索引让慢查询降到 12ms\n再给一条可改点：补上压测数据  '
    const bubbles = bubblesOf([question('iq-1', { answer: '答一', score: 6, comment: raw })])

    expect(bubbles[1].comment).toBe(raw)
    expect(bubbles[1].comment).toHaveLength(raw.length)
  })

  it('超长点评不截断（与作答器 MAX_ANSWER_CHARS 无关）', () => {
    const longComment = '点'.repeat(200)
    const bubbles = bubblesOf([question('iq-1', { answer: '答一', score: 6, comment: longComment })])

    expect(bubbles[1].comment).toBe(longComment)
    expect(bubbles[1].comment).toHaveLength(200)
  })
})
