import { Button } from './Button'

export interface PaginationProps {
  /** 当前页码（从 1 起） */
  page: number
  /** 每页条数（与服务端 `limit` 同一口径） */
  pageSize: number
  /** 命中总数（服务端返回的 `total`，不是本页条数） */
  total: number
  /** 页码变化回调；越界页码由组件自己拦住 */
  onChange: (page: number) => void
  /** 无障碍名称，各列表各自区分（如「技术清单分页」） */
  label?: string
}

/**
 * 列表分页器：上一页 / 下一页 + 页码与总数。
 *
 * 只渲染一页时返回 `null`（没有可翻的内容，多一行反而干扰）；计数与页码用等宽数字，
 * 翻页时状态文字不抖动。数据始终由服务端按 `page` / `limit` 查询，组件不缓存任何条目。
 */
export function Pagination({ page, pageSize, total, onChange, label = '列表分页' }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / Math.max(1, pageSize)))
  if (pageCount <= 1) return null

  const current = Math.min(Math.max(page, 1), pageCount)
  return (
    <nav className="sc-pager" aria-label={label}>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={current <= 1}
        onClick={() => onChange(current - 1)}
        aria-label={`${label}：上一页`}
      >
        上一页
      </Button>
      <span className="sc-pager__status" aria-live="polite">
        第 {current} / {pageCount} 页 · 共 {total} 条
      </span>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={current >= pageCount}
        onClick={() => onChange(current + 1)}
        aria-label={`${label}：下一页`}
      >
        下一页
      </Button>
    </nav>
  )
}
