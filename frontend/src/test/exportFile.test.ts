import { describe, expect, it, vi, afterEach } from 'vitest'
import { ApiError } from '../api/client'
import { clipboardErrorMessage, copyPlainText } from '../lib/exportFile'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('r147 copyPlainText（A2 唯一实现）', () => {
  it('能力不足（node 环境无 clipboard）抛 CLIPBOARD_UNAVAILABLE 的中文指引', async () => {
    await expect(copyPlainText('内容')).rejects.toMatchObject({
      code: 'CLIPBOARD_UNAVAILABLE',
      message: '当前浏览器不支持剪贴板复制，请改用导出手动保存',
    })
  })

  it('能力就绪时调用 writeText 原文零变换', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    await copyPlainText('**原文**')
    expect(writeText).toHaveBeenCalledWith('**原文**')
  })
})

describe('r147 clipboardErrorMessage（按钮名可配）', () => {
  it('ApiError 用自带 message（能力不足的指引优先）', () => {
    const error = new ApiError('CLIPBOARD_UNAVAILABLE', '当前浏览器不支持剪贴板复制，请改用导出手动保存', 0, true)
    expect(clipboardErrorMessage(error, '导出 Markdown')).toBe('当前浏览器不支持剪贴板复制，请改用导出手动保存')
  })

  it('权限/安全拒绝单独说明，并带上本页的导出按钮名', () => {
    const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' })
    expect(clipboardErrorMessage(denied, '导出 Markdown')).toBe('浏览器拒绝访问剪贴板，请改用「导出 Markdown」手动保存')
    const insecure = Object.assign(new Error('sec'), { name: 'SecurityError' })
    expect(clipboardErrorMessage(insecure, '导出 .md')).toBe('浏览器拒绝访问剪贴板，请改用「导出 .md」手动保存')
  })

  it('未知错误兜底带按钮名', () => {
    expect(clipboardErrorMessage(new Error('boom'), '导出 Markdown')).toBe('复制失败，请改用「导出 Markdown」手动保存')
    expect(clipboardErrorMessage(undefined, '导出 .md')).toBe('复制失败，请改用「导出 .md」手动保存')
  })
})
