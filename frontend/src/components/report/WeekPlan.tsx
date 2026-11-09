import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Report } from '../../api/types'
import { useLearnProgress } from '../../state/learnProgress'
import {
  PLAN_DAY_COUNT,
  PLAN_EMPTY_NOTICE,
  PLAN_LEGACY_NOTICE,
  PLAN_LOCAL_ONLY_NOTICE,
  PLAN_MINUTES,
  PLAN_VERSION,
  buildStudyPlan,
  isDayDone,
  parsePlanState,
  parseStoredPlan,
  planStateStorageKey,
  planStats,
  planStorageKey,
  type PlanMinutes,
  type PlanState,
  type StudyPlan,
} from '../../lib/studyPlan'
import { Card } from '../ui/Card'

export interface WeekPlanProps {
  report: Report
  /** 账号作用域：计划与打卡按账号 + 报告分开存，换账号不会看到上一个人的进度。 */
  userId: string
}

const DEFAULT_MINUTES: PlanMinutes = 30

/** 读打卡状态：存储不可用（隐私模式 / 配额满）时退回空状态，不影响计划展示。 */
function readState(key: string): PlanState {
  try {
    return (
      parsePlanState(window.localStorage.getItem(key)) ?? {
        version: PLAN_VERSION,
        daily_minutes: DEFAULT_MINUTES,
        done: {},
      }
    )
  } catch {
    return { version: PLAN_VERSION, daily_minutes: DEFAULT_MINUTES, done: {} }
  }
}

function writeState(key: string, state: PlanState): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(state))
  } catch {
    // 忽略：打卡只是本地体验，存不下也不阻塞学习计划。
  }
}

function readPlan(key: string): StudyPlan | null {
  try {
    return parseStoredPlan(window.localStorage.getItem(key))
  } catch {
    return null
  }
}

function writePlan(key: string, plan: StudyPlan): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(plan))
  } catch {
    // 忽略：计划可从报告确定性重算，快照只是为了让跨会话的任务顺序稳定。
  }
}

/**
 * 「7 天学习计划」（r41 功能 B · B1 纯前端确定性排程）。
 *
 * 计划来自报告短板 + 站内教程目录 + 本地已读小节：按每日可用时长装箱到 7 天，
 * 任务粒度打卡。**打卡不进评分、不调接口**，计划与打卡都只存本机浏览器（界面上明说）。
 */
export function WeekPlan({ report, userId }: WeekPlanProps) {
  const learned = useLearnProgress()
  const stateKey = useMemo(
    () => planStateStorageKey(userId, report.id),
    [userId, report.id],
  )
  const planKey = useMemo(() => planStorageKey(userId, report.id), [userId, report.id])
  const [planState, setPlanState] = useState<PlanState>(() => readState(stateKey))

  // 换账号 / 换报告时切到对应的本地状态，而不是沿用上一份报告的打卡。
  useEffect(() => {
    setPlanState(readState(stateKey))
  }, [stateKey])

  const minutes = planState.daily_minutes

  const plan = useMemo<StudyPlan>(() => {
    const stored = readPlan(planKey)
    if (stored !== null && stored.report_id === report.id && stored.daily_minutes === minutes) {
      return stored
    }
    return buildStudyPlan(report, { dailyMinutes: minutes, learned })
  }, [learned, minutes, planKey, report])

  // 快照落本地：跨会话保持同一份任务顺序（打卡按 task.id，重算不会丢已完成项）。
  useEffect(() => {
    if (plan.days.length > 0) writePlan(planKey, plan)
  }, [plan, planKey])

  const toggleTask = (id: string) => {
    setPlanState((previous) => {
      const done = { ...previous.done }
      if (done[id] === true) delete done[id]
      else done[id] = true
      const next: PlanState = { ...previous, done }
      writeState(stateKey, next)
      return next
    })
  }

  const changeMinutes = (value: PlanMinutes) => {
    setPlanState((previous) => {
      const next: PlanState = { ...previous, daily_minutes: value }
      writeState(stateKey, next)
      return next
    })
  }

  if (report.weakness_map === null) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">7 天学习计划</h3>
        </div>
        <p className="sc-coach-note">{PLAN_LEGACY_NOTICE}</p>
      </Card>
    )
  }

  if (plan.days.length === 0) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">7 天学习计划</h3>
        </div>
        <p className="sc-coach-note">{PLAN_EMPTY_NOTICE}</p>
      </Card>
    )
  }

  const stats = planStats(plan, planState.done)

  return (
    <Card className="sc-coach-block">
      <div className="sc-coach-blockhead">
        <h3 className="sc-coach-blocktitle">7 天学习计划</h3>
        <p className="sc-coach-meta">{`已完成 ${stats.completed} / ${stats.total} 项 · ${stats.percent}%`}</p>
      </div>
      <p className="sc-coach-note">{PLAN_LOCAL_ONLY_NOTICE}</p>

      <div className="sc-plan-duration" role="group" aria-label="每天可用时长">
        <span className="sc-plan-duration-label">每天可用</span>
        {PLAN_MINUTES.map((value) => (
          <button
            type="button"
            key={value}
            className={
              value === minutes ? 'sc-plan-duration-btn is-active' : 'sc-plan-duration-btn'
            }
            aria-pressed={value === minutes}
            onClick={() => changeMinutes(value)}
          >
            {value} 分钟
          </button>
        ))}
      </div>

      <div
        className="sc-plan-progress"
        role="progressbar"
        aria-label="计划完成度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={stats.percent}
      >
        <span style={{ width: `${stats.percent}%` }} />
      </div>

      <ol className="sc-plan-list">
        {plan.days.map((day) => {
          const dayDone = isDayDone(day, planState.done)
          return (
            <li className={dayDone ? 'sc-plan-day is-done' : 'sc-plan-day'} key={day.day}>
              <div className="sc-plan-dayhead">
                <span className="sc-plan-daynum sc-mono">{`Day ${day.day}`}</span>
                <span className="sc-plan-dayminutes">{`约 ${day.minutes} 分钟`}</span>
                {dayDone ? <span className="sc-plan-daystate">已完成</span> : null}
              </div>
              <div className="sc-plan-tasks">
                {day.tasks.map((task) => (
                  <div className="sc-plan-task" key={task.id}>
                    <label className="sc-plan-taskhead">
                      <input
                        type="checkbox"
                        checked={planState.done[task.id] === true}
                        onChange={() => toggleTask(task.id)}
                      />
                      <span className="sc-plan-tasklabel">{task.title}</span>
                    </label>
                    <div className="sc-plan-taskmeta">
                      <span>{`约 ${task.est_min} 分钟 · ${task.reason}`}</span>
                      <Link className="sc-plan-taskgo" to={task.href}>
                        去学习 →
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
              {day.day === PLAN_DAY_COUNT && plan.truncated ? (
                <p className="sc-plan-truncated">本周排不完，下周继续</p>
              ) : null}
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
