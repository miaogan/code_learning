import { describe, expect, it } from 'vitest'
import {
  EXPORT_MAX_BASE_CHARS,
  EXPORT_PREFIX,
  exportFileName,
  sanitizeFileBase,
} from '../lib/exportName'

/** 固定本地时间，让日期回退断言与运行时区无关（2026-11-01 本地时间）。 */
const FIXED_NOW = new Date(2026, 10, 1)
const FALLBACK_NAME = `${EXPORT_PREFIX}2026-11-01.md`

describe('sanitizeFileBase', () => {
  it('正常简历名：只去扩展名，中文与空格原样保留', () => {
    expect(sanitizeFileBase('简历.pdf')).toBe('简历')
    expect(sanitizeFileBase('张三-简历 2026.pdf')).toBe('张三-简历 2026')
  })

  it('路径段剥离：a/b.pdf 与 C:\\x\\c.pdf 只剩文件名', () => {
    expect(sanitizeFileBase('a/b.pdf')).toBe('b')
    expect(sanitizeFileBase('C:\\简历\\c.docx')).toBe('c')
  })

  it('Windows 非法字符剥离（冒号与问号），不剥中文字面', () => {
    expect(sanitizeFileBase('resume:2024?.docx')).toBe('resume2024')
    // `/` 与 `\` 是路径分隔符，已在第 2 步按基名切分剥离，故不放进本组
    expect(sanitizeFileBase('简历*?<>|".pdf')).toBe('简历')
  })

  it('空名 / 缺失 / 全空白 → 空串（交给日期回退）', () => {
    expect(sanitizeFileBase(null)).toBe('')
    expect(sanitizeFileBase(undefined)).toBe('')
    expect(sanitizeFileBase('')).toBe('')
    expect(sanitizeFileBase('   ')).toBe('')
  })

  it('无扩展名与未知后缀原样保留（不误删正文里的点）', () => {
    expect(sanitizeFileBase('简历')).toBe('简历')
    expect(sanitizeFileBase('简历.txt.bak')).toBe('简历.txt.bak')
    expect(sanitizeFileBase('c.v')).toBe('c.v')
  })

  it('超长名按 code point 截断到 120（中文不被切一半）', () => {
    const longName = '中'.repeat(EXPORT_MAX_BASE_CHARS + 60)
    const cleaned = sanitizeFileBase(`${longName}.pdf`)
    expect(Array.from(cleaned)).toHaveLength(EXPORT_MAX_BASE_CHARS)
    expect(cleaned).toBe('中'.repeat(EXPORT_MAX_BASE_CHARS))
  })

  it('首部空白与尾部点被去掉（Windows 会吞尾点）', () => {
    expect(sanitizeFileBase(' 简历.pdf')).toBe('简历')
    expect(sanitizeFileBase('简历..pdf')).toBe('简历')
  })

  it('大小写扩展名：.PDF / .DocX 同样视为简历扩展名', () => {
    expect(sanitizeFileBase('简历.PDF')).toBe('简历')
    expect(sanitizeFileBase('简历.DocX')).toBe('简历')
  })
})

describe('exportFileName', () => {
  it('正常：简历润色-<原名>.md', () => {
    expect(exportFileName('简历.pdf')).toBe(`${EXPORT_PREFIX}简历.md`)
  })

  it('路径段：取最后一段文件名', () => {
    expect(exportFileName('a/b.pdf')).toBe(`${EXPORT_PREFIX}b.md`)
  })

  it('非法字符：清洗后仍可导出，不抛错', () => {
    expect(exportFileName('resume:2024?.docx')).toBe(`${EXPORT_PREFIX}resume2024.md`)
  })

  it('空名回退日期格式：简历润色-<yyyy-mm-dd>.md', () => {
    expect(exportFileName(null, FIXED_NOW)).toBe(FALLBACK_NAME)
    expect(exportFileName(undefined, FIXED_NOW)).toBe(FALLBACK_NAME)
    expect(exportFileName('   ', FIXED_NOW)).toBe(FALLBACK_NAME)
    expect(exportFileName('??:', FIXED_NOW)).toBe(FALLBACK_NAME)
  })

  it('无扩展名：不再追加二次扩展名', () => {
    expect(exportFileName('简历')).toBe(`${EXPORT_PREFIX}简历.md`)
  })

  it('超长名：截断后仍是可读的 .md', () => {
    const name = exportFileName(`${'中'.repeat(EXPORT_MAX_BASE_CHARS + 60)}.pdf`)
    expect(name.startsWith(EXPORT_PREFIX)).toBe(true)
    expect(name.endsWith('.md')).toBe(true)
    expect(Array.from(name.slice(EXPORT_PREFIX.length, -'.md'.length)).length).toBeLessThanOrEqual(
      EXPORT_MAX_BASE_CHARS,
    )
  })

  it('大小写扩展名：同一结果，不出现「简历.PDF.md」', () => {
    expect(exportFileName('简历.PDF')).toBe(`${EXPORT_PREFIX}简历.md`)
    expect(exportFileName('简历.DocX')).toBe(`${EXPORT_PREFIX}简历.md`)
  })

  it('前缀与长度常量对外可见（页面/检查器共用同一口径）', () => {
    expect(EXPORT_PREFIX).toBe('简历润色-')
    expect(EXPORT_MAX_BASE_CHARS).toBe(120)
  })
})
