import { describe, expect, it } from 'vitest'
import { parsePromptBlocks, splitInlineCode } from '../lib/promptCode'

describe('parsePromptBlocks', () => {
  it('无围栏：恰好一个 text 块，内容与入参逐字相等（既有 80 题零回归的前提）', () => {
    const prompt = '下列关于 JavaScript 事件循环的说法，正确的是？'
    expect(parsePromptBlocks(prompt)).toEqual([{ type: 'text', content: prompt }])
  })

  it('无围栏但含行内反引号：仍只有一个 text 块，反引号原样保留', () => {
    const prompt = '在 CPython 中，`list.append()` 是 O(1) 摊还复杂度。'
    const blocks = parsePromptBlocks(prompt)
    expect(blocks).toHaveLength(1)
    expect(blocks[0]).toEqual({ type: 'text', content: prompt })
  })

  it('单个围栏：切成 [text, code]，语言标注留在 code.lang', () => {
    const blocks = parsePromptBlocks('看下面这段代码\n```python\nprint(1)\n```\n输出是什么？')
    expect(blocks).toEqual([
      { type: 'text', content: '看下面这段代码' },
      { type: 'code', content: 'print(1)', lang: 'python' },
      { type: 'text', content: '输出是什么？' },
    ])
  })

  it('多个围栏：text / code 交替，顺序不被打乱', () => {
    const blocks = parsePromptBlocks('A\n```js\nconst a = 1\n```\nB\n```\nplain\n```\nC')
    expect(blocks.map((block) => block.type)).toEqual(['text', 'code', 'text', 'code', 'text'])
    expect(blocks[1]).toEqual({ type: 'code', content: 'const a = 1', lang: 'js' })
    expect(blocks[3]).toEqual({ type: 'code', content: 'plain', lang: '' })
  })

  it('CRLF：换行先归一，代码块内容不含 \\r', () => {
    const blocks = parsePromptBlocks('题干\r\n```ts\r\nlet x = 1\r\n```\r\n结论')
    const code = blocks.find((block) => block.type === 'code')
    expect(code).toEqual({ type: 'code', content: 'let x = 1', lang: 'ts' })
    expect(blocks[0]).toEqual({ type: 'text', content: '题干' })
  })

  it('未闭合围栏：不抛错，整体退化为单个 text 块（不吞内容）', () => {
    const prompt = '题干\n```python\nprint(1)'
    expect(() => parsePromptBlocks(prompt)).not.toThrow()
    const blocks = parsePromptBlocks(prompt)
    expect(blocks).toHaveLength(1)
    expect(blocks[0].type).toBe('text')
    expect(blocks[0].type === 'text' ? blocks[0].content : '').toBe(prompt)
  })

  it('空串 / 纯空白：仍是单个 text 块（页面不炸）', () => {
    expect(parsePromptBlocks('')).toEqual([{ type: 'text', content: '' }])
    expect(parsePromptBlocks('   ')).toEqual([{ type: 'text', content: '   ' }])
  })
})

describe('splitInlineCode', () => {
  it('成对反引号切出 code 段，其余为 text 段', () => {
    expect(splitInlineCode('用 `const` 声明对象')).toEqual([
      { type: 'text', content: '用 ' },
      { type: 'code', content: 'const' },
      { type: 'text', content: ' 声明对象' },
    ])
  })

  it('落单的最后一个反引号按普通字符处理（不吞尾巴）', () => {
    expect(splitInlineCode('a `b` c `d')).toEqual([
      { type: 'text', content: 'a ' },
      { type: 'code', content: 'b' },
      { type: 'text', content: ' c `d' },
    ])
  })

  it('无反引号：单个 text 段，内容不变', () => {
    expect(splitInlineCode('没有行内代码')).toEqual([{ type: 'text', content: '没有行内代码' }])
  })
})
