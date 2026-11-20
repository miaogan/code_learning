/**
 * Markdown 复制 / 导出的**唯一实现**（r147 A1/A2：此前三页逐字重复）。
 *
 * 口径：
 * - 下载是 `Blob → createObjectURL → <a download> → click → revoke`，
 *   mime 默认 `text/markdown;charset=utf-8`（当前全部调用方都是 Markdown 导出）；
 * - 复制前置能力判断（非安全上下文 / 旧浏览器直接抛 `CLIPBOARD_UNAVAILABLE`），
 *   与 `clipboardErrorMessage` 配套给出「改用导出」的中文指引；
 * - 错误文案里的导出按钮名走参数（各页按钮文案不同：报告/修文「导出 .md」、卷宗「导出 Markdown」）。
 * - `downloadTextFile` 依赖 DOM，vitest（node 环境）不测；`copyPlainText` 的
 *   能力判断与 `clipboardErrorMessage` 是纯函数，有测试钉住。
 */

import { ApiError } from '../api/client'

/** 把文本落成浏览器下载（不关心内容来源；调用方负责拿正文与决定文件名）。 */
export function downloadTextFile(text: string, filename: string, mimeType = 'text/markdown;charset=utf-8'): void {
  const blob = new Blob([text], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** 复制纯文本；能力不足（http 页面 / 旧浏览器）抛带中文指引的 ApiError，权限拒绝交给浏览器异常。 */
export async function copyPlainText(text: string): Promise<void> {
  if (typeof navigator.clipboard?.writeText !== 'function') {
    throw new ApiError('CLIPBOARD_UNAVAILABLE', '当前浏览器不支持剪贴板复制，请改用导出手动保存', 0, true)
  }
  await navigator.clipboard.writeText(text)
}

/** 复制失败的中文文案：能力不足用 ApiError 自带 message；权限/安全拒绝单独说；其余兜底。 */
export function clipboardErrorMessage(error: unknown, exportLabel = '导出 .md'): string {
  if (error instanceof ApiError) return error.message || `复制失败，请改用「${exportLabel}」手动保存`
  const name = typeof error === 'object' && error !== null ? (error as { name?: unknown }).name : null
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return `浏览器拒绝访问剪贴板，请改用「${exportLabel}」手动保存`
  }
  return `复制失败，请改用「${exportLabel}」手动保存`
}
