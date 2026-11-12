/**
 * 首页「今日计划」（r96）：把 7 天计划里的**今天**搬到用户每天第一眼看到的页面。
 *
 * 只读卡片，刻意不做勾选：打卡的唯一入口仍在报告页 `WeekPlan`（那份状态有云端合并与防抖上推），
 * 首页复刻一套写路径只会造出第二种同步语义。这里只回答两件事——今天还剩什么、点哪里接着做。
 *
 * 没有任何计划可展示时**整块不渲染**（无报告 / 报告没有薄弱地图 / 无短板可排），
 * 新用户首页不出现空壳卡片。
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { PlanState, Report } from '../../api/types'
import { useLearnProgress } from '../../state/learnProgress'
import { useAsync } from '../../lib/useAsync'
import {
  PLAN_MINUTES,
  buildStudyPlan,
  isoDay,
  todayPlan,
  type PlanMinutes,
  type StudyPlan,
  type TodayPlanView,
} from '../../lib/studyPlan'

interface TodayData {
  report: Report | null
  state: PlanState | null
}

/** 报告 / 计划状态缺失都按「没有」处理：首页是入口页，不该因为一次读失败弹错误条。 */
async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch {
    return null
  }
}

function minutesOf(state: PlanState | null): PlanMinutes {
  const value = state?.daily_minutes
  return value !== undefined && PLAN_MINUTES.includes(value) ? value : 30
}

function doneOf(state: PlanState | null): Record<string, true> {
  const done: Record<string, true> = {}
  for (const [taskId, flag] of Object.entries(state?.done ?? {})) {
    if (flag === true) done[taskId] = true
  }
  return done
}

function metaText(view: TodayPlanView): string {
  switch (view.status) {
    case 'active':
      return `还剩 ${view.remaining} 项`
    case 'done':
      return `今天的 ${view.tasks.length} 项都做完了`
    case 'idle':
      return '还没开始计时：Day 1 就是开始那天'
    default:
      return `7 天已经过完，还有 ${view.openDays} 天没做完`
  }
}

export function TodayPlan() {
  const learned = useLearnProgress()
  const dataAsync = useAsync<TodayData>(async (signal) => {
    const report = await optional(api.latestReport(signal))
    const state = report === null ? null : await optional(api.planState(report.id, signal))
    return { report, state }
  }, [])
  const data = dataAsync.data

  const view = useMemo(() => {
    if (data === null || data.report === null) return null
    const plan: StudyPlan = buildStudyPlan(data.report, {
      dailyMinutes: minutesOf(data.state),
      learned,
    })
    if (plan.days.length === 0) return null
    return todayPlan(plan, doneOf(data.state), data.state?.started_on ?? '', isoDay(new Date()))
  }, [data, learned])

  if (view === null) return null

  return (
    <section className="sc-today" aria-label="今日计划">
      <div className="sc-today-head">
        <span className="sc-today-tag sc-mono">
          {view.day === null ? '今日计划' : `今日计划 · Day ${view.day}`}
        </span>
        <span className="sc-today-meta">{metaText(view)}</span>
      </div>

      {view.status === 'active' || view.status === 'done' ? (
        <ul className="sc-today-tasks">
          {view.tasks.map((task) => (
            <li className="sc-today-task" key={task.id}>
              <span
                className={task.id === view.nextTask?.id ? 'sc-today-dot is-next' : 'sc-today-dot'}
                aria-hidden="true"
              />
              <Link className="sc-today-link" to={task.href}>
                {task.title}
              </Link>
              <span className="sc-today-min sc-mono">{`${task.est_min}m`}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="sc-today-hint">
          {view.status === 'idle'
            ? '打开医案点「今天开始」，这 7 天就会按日期推进。'
            : '去医案点「从今天重新排」即可接着做，已打卡的任务不会丢。'}
        </p>
      )}

      <div className="sc-today-actions">
        {view.nextTask !== null && view.status !== 'idle' ? (
          <Link className="sc-today-next" to={view.nextTask.href}>
            接着做：{view.nextTask.title}
          </Link>
        ) : null}
        <Link className="sc-today-go" to="/report">
          {view.status === 'idle' ? '去医案开始 →' : '去医案看完整计划 →'}
        </Link>
      </div>
    </section>
  )
}
