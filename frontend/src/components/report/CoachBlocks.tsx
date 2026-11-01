import type { Report } from '../../api/types'
import { ResumePointers } from './ResumePointers'
import { RoleFitCard } from './RoleFitCard'
import { WeaknessMap } from './WeaknessMap'

export interface CoachBlocksProps {
  report: Report
}

/**
 * 「提升路线」分区（DESIGN r7 §1）：把三块旁挂区块收口在**一个**容器里。
 *
 * 为什么要有这一层：三块的顺序（薄弱 → 简历 → 竞争力）与分隔是唯一容易被后续改动打散的东西，
 * 集中在 `CoachBlocks` 后 `ReportPage` 只插一行，主轴（概览卡 + 3–5 条短板）结构风险最小。
 * 三块**只读** `report` 上的原值，不做 `?? []` 合并（`null` 旧报告 / `[]` 空数据语义不同）。
 */
export function CoachBlocks({ report }: CoachBlocksProps) {
  return (
    <section className="sc-coach" aria-labelledby="coach-blocks-title">
      <div className="sc-coach-head">
        <h2 className="sc-coach-title" id="coach-blocks-title">
          提升路线
        </h2>
        <p className="sc-coach-sub">先把薄弱点补上，再改简历表达，最后对齐目标岗位</p>
      </div>

      <WeaknessMap items={report.weakness_map} />
      <ResumePointers pointers={report.resume_pointers} notice={report.resume_pointers_notice} />
      <RoleFitCard roleFit={report.role_fit} />
    </section>
  )
}
