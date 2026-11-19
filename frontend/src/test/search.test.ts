import { describe, expect, it } from 'vitest'
import type { RagChunkItem } from '../api/types'
import { isSearchable, normalizeQuery, previewText, questionHref, ragHref } from '../lib/search'

const qs = (params: Record<string, string>): string => new URLSearchParams(params).toString()

describe('全站检索纯函数', () => {
  it('normalizeQuery 把全角空格转半角并压平连续空白', () => {
    expect(normalizeQuery('　  索引  优化　')).toBe('索引 优化')
    expect(normalizeQuery('a\n\tb   c')).toBe('a b c')
  })

  it('normalizeQuery 空串 / 纯空白归一为空串', () => {
    expect(normalizeQuery('')).toBe('')
    expect(normalizeQuery('　 \t\n')).toBe('')
  })

  it('isSearchable 只认字母 / 数字 / 汉字，纯标点不触发检索', () => {
    expect(isSearchable('')).toBe(false)
    expect(isSearchable(' ，。！')).toBe(false)
    expect(isSearchable('索引')).toBe(true)
    expect(isSearchable('BM25')).toBe(true)
  })

  it('questionHref 带方向与子方向，且不带 limit（命中项不替用户决定题量）', () => {
    expect(questionHref({ direction: 'Agent', sub_direction: '工具调用' })).toBe(
      `/practice?${qs({ direction: 'Agent', sub: '工具调用' })}`,
    )
  })

  it('questionHref 缺子方向 / 缺方向时降级为更短的链接', () => {
    expect(questionHref({ direction: 'Agent', sub_direction: '' })).toBe(
      `/practice?${qs({ direction: 'Agent' })}`,
    )
    expect(questionHref({ direction: '  ', sub_direction: '' })).toBe('/practice')
  })

  it('previewText 压平换行与连续空白', () => {
    expect(previewText('第一行\n第二行   第三段')).toBe('第一行 第二行 第三段')
  })

  it('previewText 超长截断加省略号，max<=0 返回空串', () => {
    expect(previewText('一二三四五', 4)).toBe('一二三四…')
    expect(previewText('一二三四五', 5)).toBe('一二三四五')
    expect(previewText('一二三', 0)).toBe('')
  })
})

/** RAG 命中项：只填跳转需要的字段，其余按契约给空值。 */
function ragItem(patch: Partial<RagChunkItem>): RagChunkItem {
  return {
    chunk_id: 'chunk-1',
    kind: 'question',
    ref_id: 'q-1',
    section_id: '',
    title: '',
    content: '',
    snippet: '',
    score: 0.01,
    ...patch,
  }
}

describe('RAG 命中项跳转（r142）', () => {
  it('教程命中跳到具体章节的对应小节锚点', () => {
    expect(
      ragHref(
        ragItem({
          kind: 'tutorial',
          ref_id: 'ch-1',
          section_id: 'sec-3',
          title: 'AI 工程 · 教程 · 小节',
        }),
      ),
    ).toBe('/learn/ch-1#tutorial-sec-3')
  })

  it('教程分片 id 的 #n 后缀不进锚点（锚点仍是小节本体）', () => {
    expect(ragHref(ragItem({ kind: 'tutorial', ref_id: 'ch-1', section_id: 'sec-2#4' }))).toBe(
      '/learn/ch-1#tutorial-sec-2',
    )
  })

  it('教程 chunk 缺 ref_id 时降级到教程目录，不生成坏链接', () => {
    expect(ragHref(ragItem({ kind: 'tutorial', ref_id: '  ', section_id: 'sec-1' }))).toBe(
      '/learn',
    )
  })

  it('题目命中按「方向 · 二级方向」带到练习页筛选', () => {
    expect(ragHref(ragItem({ title: 'AI 工程 · LLM 与 RAG' }))).toBe(
      `/practice?${qs({ direction: 'AI 工程', sub: 'LLM 与 RAG' })}`,
    )
  })

  it('题目命中缺二级方向时只带方向，两边都缺时回退到练习页', () => {
    expect(ragHref(ragItem({ title: '前端' }))).toBe(`/practice?${qs({ direction: '前端' })}`)
    expect(ragHref(ragItem({ title: '' }))).toBe('/practice')
  })
})
