import { EmptyState } from '../components/ui/EmptyState'

/** r75 未注册路由：保留全局壳层，并给出明确原因和回首页出口。 */
export default function NotFoundPage() {
  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">页面不存在</h1>
      </header>
      <EmptyState
        reason="这个地址不存在，可能是链接过期或拼写有误"
        actionLabel="回首页"
        actionTo="/"
      />
    </section>
  )
}
