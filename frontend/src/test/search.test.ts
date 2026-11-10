import { describe, expect, it } from 'vitest'
import { isSearchable, normalizeQuery, previewText, questionHref } from '../lib/search'

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
