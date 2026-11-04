import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Report } from '../../api/types'
import {
  PLAN_DAY_COUNT,
  PLAN_EMPTY_NOTICE,
  PLAN_LEGACY_NOTICE,
  buildWeekPlan,
  parsePlanProgress,
  weekPlanStorageKey,
} from '../../lib/reportPlan'
import { Card } from '../ui/Card'

export interface WeekPlanProps {
  report: Report
  /** 账号作用域：打卡状态按账号 + 报告分开存，换账号不会看到上一个人的进度。 */
  userId: string
}

/** 读本地打卡：存储不可用（隐私模式 / 配额满）时按「一天未完成」，不影响计划展示。 */
function readProgress(key: string): number[] {
  try {
    return parsePlanProgress(window.localStorage.getItem(key))
  } catch {
    return []
  }
}

function writeProgress(key: string, days: number[]): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(days))
  } catch {
    // 忽略：打卡只是本地体验，存不下也不阻塞学习计划
  }
}

/**
 * 「7 天补短板计划」（调研改造 3 · 对标 LeetCode Study Plan）。
 *
 * 把报告里已有的短板翻译成 7 个可执行的日子：前 3 天按薄弱分组做专项练习 + 读对应课程，
 * 后 4 天固定为错题清零、综合练习、模拟笔试、模拟面试 + 复盘。
 * 任务全部可点击回到站内真实入口，打卡状态只存本地（按账号 + 报告 id 隔离）。
 */
export function WeekPlan({ report, userId }: WeekPlanProps) {
  const plan = useMemo(() => buildWeekPlan(report), [report])
  const storageKey = useMemo(
    () => weekPlanStorageKey(userId, report.id),
    [userId, report.id],
  )
  const [done, setDone] = useState<number[]>(() => readProgress(storageKey))

  // 换账号 / 换报告时切到对应的本地进度，而不是沿用上一份报告的打勾。
  useEffect(() => {
    setDone(readProgress(storageKey))
  }, [storageKey])

  const toggle = (day: number) => {
    setDone((previous) => {
      const next = previous.includes(day)
        ? previous.filter((value) => value !== day)
        : [...previous, day].sort((a, b) => a - b)
      writeProgress(storageKey, next)
      return next
    })
  }

  if (report.weakness_map === null) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">7 天补短板计划</h3>
        </div>
        <p className="sc-coach-note">{PLAN_LEGACY_NOTICE}</p>
      </Card>
    )
  }

  if (plan.length === 0) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">7 天补短板计划</h3>
        </div>
        <p className="sc-coach-note">{PLAN_EMPTY_NOTICE}</p>
      </Card>
    )
  }

  const doneCount = done.filter((day) => plan.some((item) => item.day === day)).length

  return (
    <Card className="sc-coach-block">
      <div className="sc-coach-blockhead">
        <h3 className="sc-coach-blocktitle">7 天补短板计划</h3>
        <p className="sc-coach-meta">{`已完成 ${doneCount} / ${PLAN_DAY_COUNT} 天`}</p>
      </div>
      <p className="sc-coach-note">
        前 3 天按最靠前的薄弱分组专项补课，后 4 天错题清零、综合练习与模拟，最后回到报告对照变化。
      </p>

      <ol className="sc-plan-list">
        {plan.map((day) => {
          const isDone = done.includes(day.day)
          return (
            <li className={isDone ? 'sc-plan-day is-done' : 'sc-plan-day'} key={day.day}>
              <div className="sc-plan-dayhead">
                <span className="sc-plan-daynum sc-mono">{`Day ${day.day}`}</span>
                <h4 className="sc-plan-daytitle">{day.title}</h4>
                <label className="sc-plan-check">
                  <input
                    type="checkbox"
                    checked={isDone}
                    onChange={() => toggle(day.day)}
                  />
                  <span>{isDone ? '已完成' : '标记完成'}</span>
                </label>
              </div>
              <p className="sc-plan-focus">{day.focus}</p>
              <div className="sc-plan-tasks">
                {day.tasks.map((task) =>
                  task.href === null ? (
                    <span className="sc-plan-task is-static" key={task.id}>
                      <span className="sc-plan-tasklabel">{task.label}</span>
                      <span className="sc-plan-taskmeta">{task.meta}</span>
                    </span>
                  ) : (
                    <Link className="sc-plan-task" to={task.href} key={task.id}>
                      <span className="sc-plan-tasklabel">{task.label}</span>
                      <span className="sc-plan-taskmeta">{task.meta}</span>
                    </Link>
                  ),
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
