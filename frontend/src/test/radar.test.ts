import { describe, expect, it } from 'vitest'
import type { RadarChapterDraft, RadarJobItem, RadarQuestionSample, RadarTechItem } from '../api/types'
import {
  ACTIVE_JOB_STATUSES,
  assessedTimeText,
  canAdopt,
  canDiscard,
  discardedNotice,
  dimensionText,
  formatCount,
  groupTechsByDay,
  isActiveJob,
  isTerminalJob,
  jobDirection,
  jobPioneerHref,
  jobPracticeHref,
  jobSubDirection,
  matchesTechQuery,
  needsTranslation,
  progressText,
  safeRepoUrl,
  stageLabel,
  starDeltaText,
  statusLabel,
  summaryText,
  techMetaText,
  sparklinePoints,
  techTagList,
  listCountText,
  verdictChipLabel,
  verdictCountText,
  whyText,
} from '../lib/radar'

function question(overrides: Partial<RadarQuestionSample> = {}): RadarQuestionSample {
  return {
    id: 'radar-1-q1',
    direction: 'AI 工程',
    sub_direction: 'Agent',
    kind: 'single',
    difficulty: 'basic',
    essentiality: 'must_know',
    prompt: '这一项技术的主要用途是什么？',
    options: [
      { key: 'A', text: '提升推理吞吐' },
      { key: 'B', text: '压缩模型体积' },
      { key: 'C', text: '加速训练' },
    ],
    answer: ['A'],
    language: 'zh',
    explanation: '连续批处理提升吞吐。',
    ...overrides,
  }
}

function job(overrides: Partial<RadarJobItem> = {}): RadarJobItem {
  return {
    job_id: 'job-1',
    tech_slug: 'github:demo/vllm',
    tech_name: 'vLLM',
    status: 'running',
    stage: 'chapter',
    progress: 20,
    chapter: null,
    questions: [],
    discarded_count: 0,
    discarded_reasons: {},
    error_message: '',
    trigger: 'manual',
    created_at: '2026-11-10T09:00:00Z',
    updated_at: '2026-11-10T09:01:00Z',
    ...overrides,
  }
}

function chapter(overrides: Partial<RadarChapterDraft> = {}): RadarChapterDraft {
  return {
    id: 'chap-1',
    title: 'vLLM 上手',
    direction: 'AI 工程',
    sub_direction: '部署与推理',
    level: 'intermediate',
    summary: '推理引擎的原理与落地。',
    sections: [],
    ...overrides,
  }
}

function tech(overrides: Partial<RadarTechItem> = {}): RadarTechItem {
  return {
    tech_slug: 'github:demo/vllm',
    name: 'vLLM',
    direction: 'AI 工程',
    sub_direction: '部署与推理',
    source_key: 'github',
    url: 'https://github.com/demo/vllm',
    summary: '高吞吐推理引擎',
    summary_zh: '高吞吐推理引擎',
    verdict: 'must_learn',
    verdict_label: '必须学',
    relevance: 5,
    adoption: 4,
    maturity: 4,
    effort: 3,
    reasons: ['命中目标方向', '热度过阈值'],
    evidence: ['github stars 12000'],
    rule_based: true,
    assessed_at: '2026-11-10T09:00:00Z',
    stars: 12000,
    star_delta_7d: 300,
    suspect: false,
    job_id: '',
    ...overrides,
  }
}

describe('r67 radar 状态文案', () => {
  it('六个状态各有中文，越界状态原样回显', () => {
    expect(statusLabel('queued')).toBe('排队中')
    expect(statusLabel('running')).toBe('生成中')
    expect(statusLabel('succeeded')).toBe('已完成')
    expect(statusLabel('adopted')).toBe('已扩充入库')
    expect(statusLabel('discarded')).toBe('已废弃')
    expect(statusLabel('failed')).toBe('生成失败')
    expect(statusLabel('weird')).toBe('weird')
  })

  it('四个阶段各有中文，越界阶段原样回显', () => {
    expect(stageLabel('chapter')).toBe('正在写学习章节')
    expect(stageLabel('questions')).toBe('正在出练习题')
    expect(stageLabel('done')).toBe('已生成完毕')
    expect(stageLabel('failed')).toBe('已中止')
    expect(stageLabel('weird')).toBe('weird')
  })

  it('在途 / 终态互斥，闭集只含排队与生成中', () => {
    expect(ACTIVE_JOB_STATUSES).toEqual(['queued', 'running'])
    expect(isActiveJob('queued')).toBe(true)
    expect(isActiveJob('running')).toBe(true)
    for (const status of ['succeeded', 'adopted', 'discarded', 'failed']) {
      expect(isActiveJob(status)).toBe(false)
      expect(isTerminalJob(status)).toBe(true)
    }
    expect(isTerminalJob('running')).toBe(false)
  })
})

describe('r67 radar 进度与出口判定', () => {
  it('在途给「阶段 · 百分比」，并对越界进度夹取', () => {
    expect(progressText(job())).toBe('正在写学习章节 · 20%')
    expect(progressText(job({ stage: 'questions', progress: 60.9 }))).toBe('正在出练习题 · 60%')
    expect(progressText(job({ progress: 130 }))).toBe('正在写学习章节 · 100%')
    expect(progressText(job({ progress: -5 }))).toBe('正在写学习章节 · 0%')
  })

  it('终态给状态名，失败附原因', () => {
    expect(progressText(job({ status: 'succeeded', stage: 'done', progress: 100 }))).toBe('已完成')
    expect(progressText(job({ status: 'adopted' }))).toBe('已扩充入库')
    expect(progressText(job({ status: 'failed', error_message: '样例生成超时，请稍后重试' }))).toBe(
      '生成失败：样例生成超时，请稍后重试',
    )
    expect(progressText(job({ status: 'failed', error_message: '' }))).toBe('生成失败')
  })

  it('只有「已完成 + 确有题」才能扩充入库', () => {
    expect(canAdopt(job({ status: 'succeeded', questions: [question()] }))).toBe(true)
    expect(canAdopt(job({ status: 'succeeded', questions: [] }))).toBe(false)
    expect(canAdopt(job({ status: 'running', questions: [question()] }))).toBe(false)
    expect(canAdopt(job({ status: 'failed', questions: [question()] }))).toBe(false)
  })

  it('在途不能废弃，已废弃不能再废弃，已完成 / 失败 / 已入库都可作废', () => {
    expect(canDiscard(job({ status: 'running' }))).toBe(false)
    expect(canDiscard(job({ status: 'queued' }))).toBe(false)
    expect(canDiscard(job({ status: 'discarded' }))).toBe(false)
    for (const status of ['succeeded', 'failed', 'adopted']) {
      expect(canDiscard(job({ status }))).toBe(true)
    }
  })

  it('丢弃提示只在有丢弃时出现，并给出条数', () => {
    expect(discardedNotice(job())).toBe('')
    expect(discardedNotice(job({ discarded_count: 2 }))).toContain('另有 2 条题未通过自检')
    expect(discardedNotice(job({ discarded_count: 2 }))).toContain('不入库')
  })
})

describe('r67 radar 读数格式化', () => {
  it('star 量级千位压成 k，非法与非正数归 0', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(-3)).toBe('0')
    expect(formatCount(Number.NaN)).toBe('0')
    expect(formatCount(999)).toBe('999')
    expect(formatCount(1200)).toBe('1.2k')
    expect(formatCount(12000)).toBe('12.0k')
  })

  it('7 日增量 0 与负数都是「持平」，正数带 +', () => {
    expect(starDeltaText(0)).toBe('持平')
    expect(starDeltaText(-10)).toBe('持平')
    expect(starDeltaText(Number.NaN)).toBe('持平')
    expect(starDeltaText(300)).toBe('+300')
    expect(starDeltaText(1500)).toBe('+1.5k')
  })

  it('四维读数一行化，顺序固定', () => {
    expect(dimensionText(tech())).toBe(
      '相关度 5/5 · 采用度 4/5 · 成熟度 4/5 · 学习成本 3/5',
    )
  })

  it('副标题按需拼接：子方向 / 规则评估 / 疑似刷 star', () => {
    expect(techMetaText(tech())).toBe(
      'AI 工程 · 部署与推理 · star 12.0k（7 日 +300） · 规则评估',
    )
    expect(techMetaText(tech({ sub_direction: '', star_delta_7d: 0, rule_based: false }))).toBe(
      'AI 工程 · star 12.0k（7 日 持平）',
    )
    expect(techMetaText(tech({ suspect: true }))).toContain('疑似刷 star，结论已降档')
  })
})

describe('r74 摘要中文化与仓库外链', () => {
  it('中文优先，没有译文时回退英文原文', () => {
    expect(summaryText(tech({ summary_zh: '高吞吐推理引擎的中文简介' }))).toBe(
      '高吞吐推理引擎的中文简介',
    )
    expect(summaryText(tech({ summary: 'High-throughput inference', summary_zh: '' }))).toBe(
      'High-throughput inference',
    )
  })

  it('外链只放行 http(s)，脏值与空值一律不渲染链接', () => {
    expect(safeRepoUrl('https://github.com/demo/vllm')).toBe('https://github.com/demo/vllm')
    expect(safeRepoUrl('  http://example.com/repo ')).toBe('http://example.com/repo')
    expect(safeRepoUrl('javascript:alert(1)')).toBe('')
    expect(safeRepoUrl('github.com/demo/vllm')).toBe('')
    expect(safeRepoUrl('   ')).toBe('')
  })

  it('只有足够长的英文摘要才值得翻，中文与短词跳过', () => {
    expect(needsTranslation('High-throughput LLM inference and serving engine')).toBe(true)
    expect(needsTranslation('高吞吐推理引擎')).toBe(false)
    expect(needsTranslation('支持 RAG 的检索框架')).toBe(false)
    expect(needsTranslation('CLI tool')).toBe(false)
    expect(needsTranslation('')).toBe(false)
  })
})

describe('r87 先锋 ↔ 国子监联动：任务方向读数与跳转链接', () => {
  it('方向读数：章节草稿优先，其次第一条题；空白值修剪，两者皆无返回空串', () => {
    expect(jobDirection(job({ chapter: chapter() }))).toBe('AI 工程')
    expect(
      jobDirection(job({ chapter: chapter({ direction: '  ' }), questions: [question()] })),
    ).toBe('AI 工程')
    expect(jobDirection(job({ chapter: chapter({ direction: ' 后端 ' }) }))).toBe('后端')
    expect(jobDirection(job())).toBe('')
    expect(jobSubDirection(job({ chapter: chapter({ sub_direction: ' Agent ' }) }))).toBe('Agent')
    expect(
      jobSubDirection(
        job({ chapter: chapter({ sub_direction: '' }), questions: [question({ sub_direction: 'RAG' })] }),
      ),
    ).toBe('RAG')
  })

  it('练习入口：只有已入库且推得出方向的任务才有，其余一律空串', () => {
    const adopted = job({ status: 'adopted', chapter: chapter() })
    const url = new URL(jobPracticeHref(adopted), 'http://localhost')
    expect(url.pathname).toBe('/practice')
    expect(url.searchParams.get('direction')).toBe('AI 工程')
    expect(url.searchParams.get('sub')).toBe('部署与推理')
    // 未入库的题不在练习池里，不给入口
    expect(jobPracticeHref(job({ status: 'succeeded', chapter: chapter() }))).toBe('')
    expect(jobPracticeHref(job({ status: 'running' }))).toBe('')
    expect(jobPracticeHref(job({ status: 'discarded' }))).toBe('')
    expect(jobPracticeHref(job({ status: 'failed' }))).toBe('')
    // 入库了但推不出方向：不猜，入口也不给
    expect(
      jobPracticeHref(
        job({ status: 'adopted', chapter: chapter({ direction: '' }), questions: [] }),
      ),
    ).toBe('')
  })

  it('先锋回链：tech 必带，name / direction 推得出才带', () => {
    const url = new URL(jobPioneerHref(job({ chapter: chapter() })), 'http://localhost')
    expect(url.pathname).toBe('/pioneer')
    expect(url.searchParams.get('tech')).toBe('github:demo/vllm')
    expect(url.searchParams.get('name')).toBe('vLLM')
    expect(url.searchParams.get('direction')).toBe('AI 工程')
    const bare = new URL(jobPioneerHref(job()), 'http://localhost')
    expect(bare.searchParams.get('tech')).toBe('github:demo/vllm')
    expect(bare.searchParams.get('name')).toBe('vLLM')
    expect(bare.searchParams.get('direction')).toBeNull()
  })
})

/** 本地时区构造 ISO，避免测试结果随 CI 时区漂移。 */
function localIso(year: number, month: number, day: number, hour: number, minute = 0): string {
  return new Date(year, month - 1, day, hour, minute).toISOString()
}

describe('r144 先锋信息流纯函数', () => {
  const now = new Date(2026, 10, 19, 18, 0) // 2026-11-19（本地）

  it('assessedTimeText 输出本地 HH:MM，坏值返回空串', () => {
    expect(assessedTimeText(localIso(2026, 11, 19, 9, 5))).toBe('09:05')
    expect(assessedTimeText('')).toBe('')
    expect(assessedTimeText('not-a-date')).toBe('')
  })

  it('groupTechsByDay 按本地日分组并保持接口顺序，今天带「今天 ·」前缀', () => {
    const items = [
      tech({ tech_slug: 'a', assessed_at: localIso(2026, 11, 19, 17, 40) }),
      tech({ tech_slug: 'b', assessed_at: localIso(2026, 11, 19, 9, 0) }),
      tech({ tech_slug: 'c', assessed_at: localIso(2026, 11, 18, 20, 0) }),
    ]
    const groups = groupTechsByDay(items, now)
    expect(groups.map((group) => group.label)).toEqual(['今天 · 11月19日 周四', '11月18日 周三'])
    expect(groups[0]?.items.map((item) => item.tech_slug)).toEqual(['a', 'b'])
    expect(groups[1]?.items.map((item) => item.tech_slug)).toEqual(['c'])
  })

  it('groupTechsByDay：assessed_at 缺失 / 坏值落「时间未记录」组，不丢条目', () => {
    const groups = groupTechsByDay(
      [tech({ tech_slug: 'x', assessed_at: '' }), tech({ tech_slug: 'y', assessed_at: 'bad' })],
      now,
    )
    expect(groups).toHaveLength(1)
    expect(groups[0]?.label).toBe('时间未记录')
    expect(groups[0]?.items.map((item) => item.tech_slug)).toEqual(['x', 'y'])
  })

  it('techTagList 出方向 / 子方向，空子方向不占位；状态标签按需出现', () => {
    expect(techTagList(tech())).toEqual(['AI 工程', '部署与推理', '规则评估'])
    expect(techTagList(tech({ rule_based: false, suspect: true }))).toEqual([
      'AI 工程',
      '部署与推理',
      '疑似刷 star',
    ])
    expect(techTagList(tech({ direction: '  ', sub_direction: '', rule_based: false }))).toEqual([])
  })

  it('matchesTechQuery 多词 AND，命中标题 / 中英摘要 / 方向 / 来源；空词全过', () => {
    const item = tech({ summary: 'high throughput inference engine' })
    expect(matchesTechQuery(item, '')).toBe(true)
    expect(matchesTechQuery(item, 'vllm')).toBe(true)
    expect(matchesTechQuery(item, '推理')).toBe(true)
    expect(matchesTechQuery(item, 'throughput 推理')).toBe(true)
    expect(matchesTechQuery(item, 'vllm 区块链')).toBe(false)
    expect(matchesTechQuery(item, 'github')).toBe(true)
  })
})

describe('r146 分面计数与折叠态依据', () => {
  it('verdictCountText 固定四档顺序，缺档补 0 而不是省略', () => {
    expect(verdictCountText({ must_learn: 8, worth_knowing: 21, watch: 18, skip: 10 })).toBe(
      '必学 8 · 选学 21 · 观望 18 · 跳过 10',
    )
    expect(verdictCountText({ must_learn: 2 })).toBe('必学 2 · 选学 0 · 观望 0 · 跳过 0')
    expect(verdictCountText(undefined)).toBe('必学 0 · 选学 0 · 观望 0 · 跳过 0')
  })

  it('verdictChipLabel 带计数；计数缺省（首屏未就绪）时退回纯文案', () => {
    expect(verdictChipLabel('必学', 8)).toBe('必学 8')
    expect(verdictChipLabel('必学', 0)).toBe('必学 0')
    expect(verdictChipLabel('必学', undefined)).toBe('必学')
  })

  it('listCountText 三种口径分开说：搜索 / 筛选同时给全量 / 常态铺四档', () => {
    const counts = { must_learn: 8, worth_knowing: 21, watch: 18, skip: 10 }
    expect(
      listCountText({ total: 57, pageCount: 10, allCount: 57, searching: false, filtering: false, counts }),
    ).toBe('共 57 项 · 必学 8 · 选学 21 · 观望 18 · 跳过 10')
    expect(
      listCountText({ total: 8, pageCount: 8, allCount: 57, searching: false, filtering: true, counts }),
    ).toBe('共 8 项 / 全部 57')
    expect(
      listCountText({ total: 8, pageCount: 3, allCount: 57, searching: true, filtering: true, counts }),
    ).toBe('本页 3 / 共 8 项')
  })

  it('whyText 取首条依据（相关度即四档结论的判定依据），空数组 / 空白给空串', () => {
    expect(whyText(tech({ reasons: ['岗位相关度 5/5（方向「AI 工程」命中你的薄弱方向）', '其他'] }))).toBe(
      '岗位相关度 5/5（方向「AI 工程」命中你的薄弱方向）',
    )
    expect(whyText(tech({ reasons: [] }))).toBe('')
    expect(whyText(tech({ reasons: ['   '] }))).toBe('')
  })
})

describe('r146 走势线坐标串', () => {
  it('sparklinePoints 少于 2 个点返回空串（一个点画不出趋势，不给假线）', () => {
    expect(sparklinePoints([])).toBe('')
    expect(sparklinePoints([12000])).toBe('')
  })

  it('sparklinePoints 首尾贴边、纵值随数据反演，全程同值画中线', () => {
    const points = sparklinePoints([100, 200, 150], 64, 18, 2)
    const coords = points.split(' ').map((pair) => pair.split(',').map(Number))
    expect(coords).toHaveLength(3)
    // 首点 x = pad，末点 x = width - pad（等距铺满）。
    expect(coords[0]?.[0]).toBe(2)
    expect(coords[2]?.[0]).toBe(62)
    // 值越大 y 越小（SVG 纵轴向下）：max 在顶，min 在底。
    const ys = coords.map((pair) => pair[1] as number)
    expect(ys[0]).toBeGreaterThan(ys[1] as number)
    expect(Math.min(...ys)).toBe(2)
    expect(Math.max(...ys)).toBe(16)
    // 全程同值：不除零，画在中线。
    const flat = sparklinePoints([5, 5, 5], 64, 18, 2).split(' ')
    expect(flat.every((pair) => pair.split(',')[1] === '9')).toBe(true)
  })
})
