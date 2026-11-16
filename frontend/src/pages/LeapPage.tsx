/**
 * r108 跃迁档案看板：把目标岗位差距、项目工程证据与面试表达汇成一屏（r56 下一阶段）。
 *
 * 严格遵守「不虚构跃迁」：三块都是站内真实事实的只读投影——岗位差距复用报告里算好的
 * `role_fit`、工程证据只报真实行数与画像溯源、面试表达沿用当场评分；四要素自检明写
 * 「不是评分」，模拟面试与 dry-run 一律不冒充生产经验。页面自身零二次统计。
 */

import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { LeapArchive, LeapExpressionItem } from '../api/types'
import { RoleFitCard } from '../components/report/RoleFitCard'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import {
  expressionSummary,
  isLeapEmpty,
  orderedProjects,
  scaleRows,
  structureParts,
} from '../lib/leapArchive'
import { formatWhen } from '../lib/format'
import { useAsync } from '../lib/useAsync'

function SectionHead({ index, title, note }: { index: string; title: string; note: string }) {
  return (
    <div className="sc-leap-head">
      <span className="sc-leap-index" aria-hidden="true">{index}</span>
      <div>
        <h2 className="sc-leap-title">{title}</h2>
        <p className="sc-leap-note">{note}</p>
      </div>
    </div>
  )
}

function ExpressionRow({ item }: { item: LeapExpressionItem }) {
  const { hits, misses } = structureParts(item.structure)
  return (
    <li className="sc-leap-expr">
      <div className="sc-leap-expr-top">
        <span className="sc-leap-expr-q">{item.prompt || '（题目未记录）'}</span>
        {item.score === null ? (
          <span className="sc-leap-expr-score is-muted">未评分</span>
        ) : (
          <span className="sc-leap-expr-score">{item.score.toFixed(1)} / 10</span>
        )}
      </div>
      <p className="sc-leap-expr-answer">{item.answer}</p>
      {item.comment ? <p className="sc-leap-expr-comment">点评：{item.comment}</p> : null}
      <div className="sc-leap-expr-chips">
        {hits.map((label) => (
          <span className="sc-chip" key={`hit-${label}`}>✓ {label}</span>
        ))}
        {misses.map((label) => (
          <span className="sc-chip is-muted" key={`miss-${label}`}>{label}</span>
        ))}
      </div>
      <p className="sc-leap-expr-hint">{item.structure.hint}</p>
    </li>
  )
}

function LeapBody({ archive }: { archive: LeapArchive }) {
  if (isLeapEmpty(archive)) {
    return (
      <EmptyState
        reason="跃迁档案还是空的：先上传简历完成画像，做一次测评并生成报告，就能看到三块证据。"
        actionLabel="去投卷"
        actionTo="/"
        altLabel="去看学堂"
        altTo="/learn"
        hints={[
          '投卷：上传简历，画像逐条溯源',
          '召对 / 科考：完成一次模拟面试或笔试',
          '医案：生成诊断报告，得到目标岗位差距',
        ]}
      />
    )
  }

  const { role_gap: roleGap, engineering, expression } = archive
  const projects = orderedProjects(engineering.projects)
  const rows = scaleRows(engineering.data_scale)

  return (
    <div className="sc-leap-grid">
      <section className="sc-leap-block">
        <SectionHead
          index="01"
          title="目标岗位差距"
          note="复用最近一份诊断报告的岗位对标；差距与优先级都在报告里算好，这里只呈现。"
        />
        {roleGap.role_fit !== null ? (
          <RoleFitCard roleFit={roleGap.role_fit} />
        ) : (
          <Card className="sc-coach-block">
            <p className="sc-coach-note">{roleGap.notice ?? '还没有目标岗位差距。'}</p>
            <Link className="sc-topbar-link" to="/report">去看诊断报告 →</Link>
          </Card>
        )}
      </section>

      <section className="sc-leap-block">
        <SectionHead
          index="02"
          title="项目工程证据"
          note="画像项目的溯源条数与站内规模事实。只报真实存在的记录，不是能力评级。"
        />
        <Card className="sc-coach-block">
          {projects.length === 0 ? (
            <p className="sc-coach-note">{engineering.notice ?? '画像里还没有项目。'}</p>
          ) : (
            <ul className="sc-leap-projects">
              {projects.map((project) => (
                <li className="sc-leap-project" key={`${project.name}-${project.period ?? ''}`}>
                  <div className="sc-leap-project-top">
                    <span className="sc-leap-project-name">{project.name}</span>
                    {project.status === 'historical' ? (
                      <span className="sc-chip is-muted">历史项目</span>
                    ) : null}
                  </div>
                  {project.role || project.period ? (
                    <p className="sc-leap-project-meta">
                      {[project.role, project.period].filter(Boolean).join(' · ')}
                    </p>
                  ) : null}
                  {project.bullets.length > 0 ? (
                    <ul className="sc-leap-bullets">
                      {project.bullets.map((bullet, index) => (
                        <li key={`${project.name}-bullet-${index}`}>{bullet}</li>
                      ))}
                    </ul>
                  ) : null}
                  <p className="sc-leap-evidence">原文溯源 {project.evidence_count} 条</p>
                </li>
              ))}
            </ul>
          )}
          {rows.length > 0 ? (
            <div className="sc-leap-scale">
              {rows.map((row) => (
                <div className="sc-leap-scale-cell" key={row.key}>
                  <span className="sc-leap-scale-num">{row.count}</span>
                  <span className="sc-leap-scale-label">{row.label}</span>
                </div>
              ))}
            </div>
          ) : null}
          {engineering.rag ? (
            <p className="sc-leap-expr-hint">
              检索索引：{engineering.rag.chunk_count} 个片段
              {engineering.rag.stale ? '（配置已变更，建议重建）' : ''}
            </p>
          ) : null}
          {engineering.radar_techs_seen > 0 ? (
            <p className="sc-leap-expr-hint">技术雷达最近采集 {engineering.radar_techs_seen} 项（站内视野，不代表个人能力）。</p>
          ) : null}
        </Card>
      </section>

      <section className="sc-leap-block sc-leap-block--wide">
        <SectionHead
          index="03"
          title="面试表达"
          note="最近已作答的发言，分数与点评沿用当场写入值；四要素只是关键词自检，不是评分。"
        />
        {expression.items.length === 0 ? (
          <Card className="sc-coach-block">
            <p className="sc-coach-note">{expression.notice ?? '还没有已作答的面试发言。'}</p>
            <Link className="sc-topbar-link" to="/interview">去做一次模拟面试 →</Link>
          </Card>
        ) : (
          <Card className="sc-coach-block">
            <p className="sc-leap-summary">{expressionSummary(expression.items)}</p>
            <ul className="sc-leap-expr-list">
              {expression.items.map((item) => (
                <ExpressionRow key={`${item.run_id}-${item.question_id}`} item={item} />
              ))}
            </ul>
            <p className="sc-leap-expr-hint">
              自检基于关键词命中，可能误判；模拟面试与 dry-run 都不是生产经验，不能作为录用保证。
            </p>
          </Card>
        )}
      </section>
    </div>
  )
}

export default function LeapPage() {
  const dataAsync = useAsync<LeapArchive>((signal) => api.leapArchive(signal), [])
  const archive = dataAsync.data

  return (
    <div className="sc-page sc-leap">
      <header className="sc-leap-hero">
        <div>
          <p className="sc-page-kicker">逃 跑 计 划 · 跃 迁 档 案</p>
          <h1 className="sc-page-title">跃迁档案</h1>
          <p className="sc-leap-hero-note">
            把目标岗位差距、项目工程证据与面试表达汇成一屏。全部来自站内真实记录，
            不把模拟评测、dry-run 或刷题量包装成生产经验。
          </p>
        </div>
        {archive ? (
          <p className="sc-leap-stamp">聚合于 {formatWhen(archive.generated_at)}</p>
        ) : null}
      </header>

      {dataAsync.status === 'loading' && archive === null ? (
        <p className="sc-coach-note">正在汇总站内证据…</p>
      ) : null}
      {dataAsync.status === 'error' ? (
        <InlineError
          message={dataAsync.error?.message ?? '跃迁档案加载失败，请稍后重试'}
          onRetry={dataAsync.reload}
        />
      ) : null}
      {archive ? <LeapBody archive={archive} /> : null}
    </div>
  )
}
