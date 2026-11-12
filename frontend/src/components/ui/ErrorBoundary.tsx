import { Component, type ReactNode } from 'react'
import { Button } from './Button'

export interface ErrorBoundaryProps {
  /** 兜底名（出现在提示与控制台里）：「页面」/「报告 · 短板区」这一类粒度名。 */
  label: string
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * 渲染错误边界（r84 §1）。
 *
 * 为什么必须有它：React 对未捕获的渲染错误会把**整棵树**卸载——r84 巡检里一个
 * `ShortfallCard` 收到缺字段的报告（`undefined.map`），整个 /report 就渲染成全黑空页。
 * 挂上边界后，坏掉的区域缩在这张卡里，页壳、导航与其余内容照常显示。
 *
 * 两个出口：「重试本区」重置 state 重新挂 children（数据是异步取的场景重挂即重取）；
 * 「刷新页面」整页重载，兜住 state 错乱类问题。
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error): void {
    // 控制台留全栈，卡片里只给人看一句话——不打断页面其余部分。
    console.error(`[${this.props.label}] 渲染失败`, error)
  }

  retry = (): void => {
    this.setState({ error: null })
  }

  reload = (): void => {
    window.location.reload()
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="sc-fault" role="alert">
        <p className="sc-fault-label">RENDER FAULT</p>
        <p className="sc-fault-title">{`${this.props.label}渲染失败，其余部分不受影响`}</p>
        <p className="sc-fault-reason">{error.message}</p>
        <div className="sc-fault-actions">
          <Button size="sm" onClick={this.retry}>
            重试本区
          </Button>
          <Button size="sm" variant="ghost" onClick={this.reload}>
            刷新页面
          </Button>
        </div>
      </div>
    )
  }
}
