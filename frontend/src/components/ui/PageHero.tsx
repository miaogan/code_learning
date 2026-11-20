import type { ReactNode } from 'react'

export interface PageHeroProps {
  /** 两位编号（如 '02'）—— kicker 最左侧的强调色读数。 */
  index: string
  /** kicker 文案（如 'PROFILE / 立传'）—— 全大写英文 + 斜杠 + 中文。 */
  kicker: string
  /** 主标题（保留各页原文案；需要强调的片段用 <HeroEm> 包住）。 */
  title: ReactNode
  /** 副文：一句话说明这页做什么，替代旧的 .sc-page-sub（支持条件表达式 / 模板串）。 */
  lead: ReactNode
  /** 右侧读数 / 状态区（可选）—— 仪器化排版，放统计或状态灯。 */
  aside?: ReactNode
  /** 标题下的操作区（可选）—— 按钮 / 链接。 */
  actions?: ReactNode
  /** 页头底部的补充提示（可选）。 */
  note?: ReactNode
}

/** 标题内的强调片段：统一用强调色（酸柠绿），语义等同首页 .sc-lab-hl。 */
export function HeroEm({ children }: { children: ReactNode }) {
  return <em className="sc-hero-em">{children}</em>
}

/**
 * 全站统一海报页头（r149）：
 * kicker 编号 → 大标题 → 副文（+ 可选操作 / 读数 / 提示）→ 底部发丝分隔线。
 * 视觉口径与首页 .sc-lab-hero 一致（等宽 kicker / 大标题 / lead 副文 / 强调色读数），
 * 让所有页面切页时的视觉重量、字号与留白节奏保持同一档。
 *
 * 用法：
 *   <PageHero index="02" kicker="PROFILE / 立传" title={<>把经历变成<HeroEm>可验证的证据</HeroEm></>} lead="……" />
 */
export function PageHero({ index, kicker, title, lead, aside, actions, note }: PageHeroProps) {
  return (
    <header className={aside === undefined ? 'sc-hero is-solo' : 'sc-hero'}>
      <div className="sc-hero-copy">
        <p className="sc-hero-kicker">
          <span className="sc-hero-kicker-idx">{index}</span> {kicker}
        </p>
        <h1 className="sc-hero-title">{title}</h1>
        <p className="sc-hero-lead">{lead}</p>
        {actions !== undefined ? <div className="sc-hero-actions">{actions}</div> : null}
        {note !== undefined ? <p className="sc-hero-note">{note}</p> : null}
      </div>
      {aside !== undefined ? <div className="sc-hero-aside">{aside}</div> : null}
    </header>
  )
}
