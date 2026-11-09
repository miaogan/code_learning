import { describe, expect, it } from 'vitest'
import { ALL_TUTORIAL_CHAPTERS } from '../lib/tutorials'
import type { TutorialChapter } from '../lib/tutorialTypes'
import {
  buildSectionDocs,
  reciprocalRankFusion,
  searchTutorials,
  type RankedHit,
} from '../lib/tutorialSearch'

function demoChapter(): TutorialChapter {
  return {
    id: 'demo-chapter',
    title: '示例章节',
    direction: 'AI 工程',
    sub_direction: '通用 AI',
    level: '基础',
    summary: '示例摘要',
    sections: [
      {
        id: 'sec-1',
        title: '第一节',
        blocks: [
          { kind: 'text', text: '开头文本' },
          { kind: 'qa', items: [{ question: '问题甲？', answer: '答案乙。' }] },
          {
            kind: 'table',
            headers: ['表头一', '表头二'],
            rows: [['单元格一', '单元格二']],
          },
          { kind: 'code', language: 'python', code: 'print(1)', caption: '代码说明' },
          { kind: 'note', tone: 'info', title: '注意标题', text: '注意正文' },
          { kind: 'list', items: ['列表项'] },
        ],
      },
      {
        id: 'sec-2',
        title: '第二节',
        blocks: [{ kind: 'text', text: '收尾文本' }],
      },
    ],
  }
}

function twinChapter(chapterId: string, sectionId: string): TutorialChapter {
  return {
    id: chapterId,
    title: '相同标题',
    direction: 'AI 工程',
    sub_direction: '通用 AI',
    level: '基础',
    summary: '相同摘要',
    sections: [
      {
        id: sectionId,
        title: '相同小节',
        blocks: [{ kind: 'text', text: '关键词 Alpha 关键词' }],
      },
    ],
  }
}

describe('buildSectionDocs', () => {
  it('把 qa / table / code / note / list 文本都纳入且顺序稳定', () => {
    const chapter = demoChapter()
    const docs = buildSectionDocs([chapter])

    expect(docs).toHaveLength(2)
    const text = docs[0].text
    expect(text).toContain('开头文本')
    expect(text).toContain('问题甲')
    expect(text).toContain('答案乙')
    expect(text).toContain('表头一')
    expect(text).toContain('单元格二')
    expect(text).toContain('print(1)')
    expect(text).toContain('代码说明')
    expect(text).toContain('注意标题')
    expect(text).toContain('列表项')

    // 片段按块与块内顺序排列：qa 早于 table，table 早于 code 的正文与说明
    expect(text.indexOf('问题甲')).toBeLessThan(text.indexOf('表头一'))
    expect(text.indexOf('表头一')).toBeLessThan(text.indexOf('print(1)'))
    expect(text.indexOf('print(1)')).toBeLessThan(text.indexOf('代码说明'))

    // 小节原序与元数据透传
    expect(docs[0]).toMatchObject({
      chapter_id: 'demo-chapter',
      section_id: 'sec-1',
      title: '第一节',
      direction: 'AI 工程',
      sub_direction: '通用 AI',
      level: '基础',
    })
    expect(docs[1].section_id).toBe('sec-2')
    expect(docs[1].text).toContain('收尾文本')

    // 同参重复调用结果完全一致
    expect(buildSectionDocs([chapter])).toEqual(docs)
  })
})

describe('searchTutorials', () => {
  it('在真实全量章节上，标题类关键词能命中对应 AI 章节', () => {
    const cases: Array<[string, string]> = [
      ['多 Agent 编排', 'ai-multi-agent'],
      ['推理服务', 'ai-inference-serving'],
      ['RAG 评审', 'ai-eval-harness'],
    ]
    cases.forEach(([query, chapterId]) => {
      const hits = searchTutorials(query, {}, ALL_TUTORIAL_CHAPTERS, 10)
      expect(hits.map((hit) => hit.chapter_id)).toContain(chapterId)
      expect(hits.length).toBeGreaterThan(0)
      hits.forEach((hit) => {
        expect(hit.source).toBe('tutorial')
        expect(hit.href).toBe(`/learn/${hit.chapter_id}#tutorial-${hit.section_id}`)
        expect(hit.snippet.length).toBeLessThanOrEqual(60)
        expect(hit.score).toBe(Math.round(hit.score * 10000) / 10000)
      })
    })
  })

  it('方向 / 子方向 / 难度过滤生效，且可组合', () => {
    const query = 'Agent'
    const base = searchTutorials(query, {}, ALL_TUTORIAL_CHAPTERS, 100)
    expect(base.length).toBeGreaterThan(0)

    const byDirection = searchTutorials(query, { direction: 'AI 工程' }, ALL_TUTORIAL_CHAPTERS, 100)
    expect(byDirection.length).toBeGreaterThan(0)
    byDirection.forEach((hit) => {
      expect(ALL_TUTORIAL_CHAPTERS.find((c) => c.id === hit.chapter_id)?.direction).toBe('AI 工程')
    })

    const bySub = searchTutorials(query, { sub_direction: 'Agent' }, ALL_TUTORIAL_CHAPTERS, 100)
    expect(bySub.length).toBeGreaterThan(0)
    bySub.forEach((hit) => {
      expect(ALL_TUTORIAL_CHAPTERS.find((c) => c.id === hit.chapter_id)?.sub_direction).toBe('Agent')
    })

    const byLevel = searchTutorials(query, { level: '高级' }, ALL_TUTORIAL_CHAPTERS, 100)
    expect(byLevel.length).toBeGreaterThan(0)
    byLevel.forEach((hit) => {
      expect(ALL_TUTORIAL_CHAPTERS.find((c) => c.id === hit.chapter_id)?.level).toBe('高级')
    })

    const combo = searchTutorials(
      query,
      { direction: 'AI 工程', sub_direction: 'Agent', level: '高级' },
      ALL_TUTORIAL_CHAPTERS,
      100,
    )
    expect(combo.length).toBeGreaterThan(0)
    combo.forEach((hit) => {
      expect(ALL_TUTORIAL_CHAPTERS.find((c) => c.id === hit.chapter_id)).toMatchObject({
        direction: 'AI 工程',
        sub_direction: 'Agent',
        level: '高级',
      })
    })
  })

  it('越界或非法的过滤值静默回落为不筛选', () => {
    const query = 'Agent'
    const base = searchTutorials(query, {}, ALL_TUTORIAL_CHAPTERS, 100)
    expect(base.length).toBeGreaterThan(0)
    expect(searchTutorials(query, { direction: '不存在的方向' }, ALL_TUTORIAL_CHAPTERS, 100)).toEqual(
      base,
    )
    expect(
      searchTutorials(query, { sub_direction: '不存在的子方向' }, ALL_TUTORIAL_CHAPTERS, 100),
    ).toEqual(base)
    expect(searchTutorials(query, { level: '中级' }, ALL_TUTORIAL_CHAPTERS, 100)).toEqual(base)
    expect(
      searchTutorials(
        query,
        { direction: '', sub_direction: '', level: '' },
        ALL_TUTORIAL_CHAPTERS,
        100,
      ),
    ).toEqual(base)
  })

  it('空 query / 无命中 / 过滤后空集都返回空数组', () => {
    expect(searchTutorials('', {}, ALL_TUTORIAL_CHAPTERS)).toEqual([])
    expect(searchTutorials('   ', {}, ALL_TUTORIAL_CHAPTERS)).toEqual([])
    expect(searchTutorials('qwertyuiopasdfghjklzxcvbnm', {}, ALL_TUTORIAL_CHAPTERS)).toEqual([])
    // react 是合法子方向但与 AI 工程无交集，过滤后文档集为空
    expect(
      searchTutorials('Agent', { direction: 'AI 工程', sub_direction: 'react' }, ALL_TUTORIAL_CHAPTERS),
    ).toEqual([])
  })

  it('排序确定：同参两次结果一致，且完全平局时按 chapter_id / section_id 升序', () => {
    const query = '多 Agent 编排'
    const first = searchTutorials(query, { direction: 'AI 工程' }, ALL_TUTORIAL_CHAPTERS, 20)
    const second = searchTutorials(query, { direction: 'AI 工程' }, ALL_TUTORIAL_CHAPTERS, 20)
    expect(first.length).toBeGreaterThan(0)
    expect(first).toEqual(second)
    for (let i = 1; i < first.length; i += 1) {
      expect(first[i - 1].score).toBeGreaterThanOrEqual(first[i].score)
    }

    // 三份内容完全相同的文档 BM25 分数必然相同，用它们验证平局规则
    const chapters = [
      twinChapter('b-chapter', 's-2'),
      twinChapter('a-chapter', 's-2'),
      twinChapter('a-chapter', 's-1'),
    ]
    const hits = searchTutorials('关键词', {}, chapters, 10)
    const ids = hits.map((hit) => `${hit.chapter_id}/${hit.section_id}`)
    expect(new Set(hits.map((hit) => hit.score)).size).toBe(1)
    expect(ids).toEqual(['a-chapter/s-1', 'a-chapter/s-2', 'b-chapter/s-2'])
    expect(searchTutorials('关键词', {}, chapters, 10)).toEqual(hits)
  })
})

describe('reciprocalRankFusion', () => {
  it('合并同 id 并按 score 降序、平局按 id 升序', () => {
    const lists: RankedHit[][] = [
      [
        { id: 'a', score: 0, source: 'tutorial' },
        { id: 'b', score: 0, source: 'tutorial' },
        { id: 'c', score: 0, source: 'question' },
      ],
      [
        { id: 'b', score: 0, source: 'tutorial' },
        { id: 'a', score: 0, source: 'question' },
        { id: 'd', score: 0, source: 'tutorial' },
      ],
    ]
    const fused = reciprocalRankFusion(lists)
    expect(fused.map((hit) => hit.id)).toEqual(['a', 'b', 'c', 'd'])

    const ab = Math.round((1 / 61 + 1 / 62) * 1000000) / 1000000
    const cd = Math.round((1 / 63) * 1000000) / 1000000
    expect(fused[0].score).toBe(ab)
    expect(fused[1].score).toBe(ab)
    expect(fused[2].score).toBe(cd)
    expect(fused[3].score).toBe(cd)
    expect(fused[0].score).toBeGreaterThan(fused[2].score)
    expect(fused[2].source).toBe('question')
    fused.forEach((hit) => {
      expect(hit.score).toBe(Math.round(hit.score * 1000000) / 1000000)
    })
  })

  it('空输入返回空数组，自定义 k 按 1/(k+rank) 计算且忽略原 score', () => {
    expect(reciprocalRankFusion([])).toEqual([])
    expect(reciprocalRankFusion([[]])).toEqual([])
    const single = reciprocalRankFusion([[{ id: 'x', score: 99, source: 'tutorial' }]], 0)
    expect(single).toEqual([{ id: 'x', score: 1, source: 'tutorial' }])
  })
})
