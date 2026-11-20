import { EmptyState } from '../components/ui/EmptyState'
import { HeroEm, PageHero } from '../components/ui/PageHero'

/** r75 未注册路由：保留全局壳层，并给出明确原因和回首页出口。 */
export default function NotFoundPage() {
  return (
    <section>
      <PageHero
        index="—"
        kicker="404 / 未注册路由"
        title={<>这里<HeroEm>没有</HeroEm>你要的页面</>}
        lead="这个地址不存在，可能是链接过期或拼写有误"
      />
      <EmptyState
        reason="也可以从下面的入口回到熟悉的地方"
        actionLabel="回首页"
        actionTo="/"
      />
    </section>
  )
}
