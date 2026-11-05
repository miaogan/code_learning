import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import type { Report } from '../../api/types'
import { roleGapLabel } from '../../lib/coach'
import {
  GUIDANCE_EMPTY_NOTICE,
  GUIDANCE_LEGACY_NOTICE,
  buildGuidance,
} from '../../lib/guidance'
import { chaptersInDirection, tutorialHref } from '../../lib/tutorials'
import { Card } from '../ui/Card'

export interface LearningDirectionCardProps {
  report: Report
}

/**
 * 「推荐学习方向」：把目标岗位模型透出的方向 + 短板课程的方向摊平成 1–3 张方向卡。
 *
 * - 主攻方向只来自 `role_fit.model.direction`（后端内置岗位模型，非前端猜测）；
 * - 延伸方向只来自 `shortfalls[].courses[].direction`（课程自身的真实方向）；
 * - 先补技能顺序 = `role_fit.first_fix`，前端绝不重排；
 * - 每个方向都落到站内真实的 `/practice?direction=` 与课程链接，不发明入口。
 */
export function LearningDirectionCard({ report }: LearningDirectionCardProps) {
  const directions = useMemo(() => buildGuidance(report), [report])

  if (report.role_fit === null) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">推荐学习方向</h3>
        </div>
        <p className="sc-coach-note">{GUIDANCE_LEGACY_NOTICE}</p>
      </Card>
    )
  }

  if (directions.length === 0) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">推荐学习方向</h3>
        </div>
        <p className="sc-coach-note">{GUIDANCE_EMPTY_NOTICE}</p>
      </Card>
    )
  }

  return (
    <Card className="sc-coach-block">
      <div className="sc-coach-blockhead">
        <h3 className="sc-coach-blocktitle">推荐学习方向</h3>
        <p className="sc-coach-meta">{`共 ${directions.length} 个方向`}</p>
      </div>

      {directions.map((item) => {
        const chapterCount = chaptersInDirection(item.direction).length
        return (
          <div className="sc-profile-dim" key={item.direction}>
            <p className="sc-role-target">
              <span>{item.kind === 'primary' ? '主攻方向' : '延伸方向'}</span>
              <span>{item.direction}</span>
            </p>
            <p className="sc-coach-note">{item.summary}</p>

            {item.skills.length > 0 ? (
              <ol className="sc-role-prio" aria-label={`${item.direction}方向先补技能`}>
                {item.skills.map((skill, index) => (
                  <li className="sc-role-prio-item" key={skill.name}>
                    <span className="sc-prio-dot" aria-hidden="true">
                      {index + 1}
                    </span>
                    <span>{skill.name}</span>
                    <span className="sc-coach-meta">
                      {`差 ${roleGapLabel(skill.gap)} 档${skill.must ? ' · 必备' : ''}`}
                    </span>
                  </li>
                ))}
              </ol>
            ) : null}

            {item.notice ? <p className="sc-coach-note">{item.notice}</p> : null}

            <div className="sc-plan-tasks">
              <Link className="sc-plan-task" to={item.practiceLink}>
                <span className="sc-plan-tasklabel">{`${item.direction}专项练习 10 题`}</span>
                <span className="sc-plan-taskmeta">方向筛选 · 全部难度</span>
              </Link>
              {chapterCount > 0 ? (
                <Link className="sc-plan-task" to={tutorialHref(item.direction)}>
                  <span className="sc-plan-tasklabel">站内教程</span>
                  <span className="sc-plan-taskmeta">{`${chapterCount} 章 · 概念到自测`}</span>
                </Link>
              ) : null}
              {item.courses.map((course) =>
                course.url === null ? (
                  <span className="sc-plan-task is-static" key={course.id}>
                    <span className="sc-plan-tasklabel">{course.title}</span>
                    <span className="sc-plan-taskmeta">{`${course.level} · 链接待更新`}</span>
                  </span>
                ) : (
                  <a
                    className="sc-plan-task"
                    key={course.id}
                    href={course.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span className="sc-plan-tasklabel">{course.title}</span>
                    <span className="sc-plan-taskmeta">{`${course.level} · 课程`}</span>
                  </a>
                ),
              )}
            </div>
          </div>
        )
      })}
    </Card>
  )
}
