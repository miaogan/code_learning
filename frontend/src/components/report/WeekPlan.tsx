import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { Report } from '../../api/types'
import { useLearnProgress } from '../../state/learnProgress'
import {
  PLAN_DAY_COUNT,
  PLAN_EMPTY_NOTICE,
  PLAN_EXPIRED_NOTICE,
  PLAN_IDLE_NOTICE,
  PLAN_LEGACY_NOTICE,
  PLAN_MINUTES,
  PLAN_SYNCED_NOTICE,
  PLAN_VERSION,
  buildStudyPlan,
  isDayDone,
  isoDay,
  mergePlanState,
  parsePlanState,
  parseStoredPlan,
  planPace,
  planPushPayload,
  planStateStorageKey,
  planStats,
  planStorageKey,
  resumeDay,
  samePlanState,
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
const PUSH_DELAY_MS = 800

/** 读打卡状态：存储不可用（隐私模式 / 配额满）时退回空状态，不影响计划展示。 */
function readState(key: string): PlanState {
  const empty: PlanState = {
    version: PLAN_VERSION,
    daily_minutes: DEFAULT_MINUTES,
    done: {},
    started_on: '',
  }
  try {
    return parsePlanState(window.localStorage.getItem(key)) ?? empty
  } catch {
    return empty
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
 * 「7 天学习计划」（r41 功能 B · B1 纯前端确定性排程 · r61 打卡上云）。
 *
 * 计划来自报告短板 + 站内教程目录 + 已读小节：按每日可用时长装箱到 7 天，任务粒度打卡。
 * **打卡不进评分**；状态以服务端为权威、本地 localStorage 只作缓存（离线时照常可勾）。
 */
export function WeekPlan({ report, userId }: WeekPlanProps) {
  const learned = useLearnProgress()
  const stateKey = useMemo(
    () => planStateStorageKey(userId, report.id),
    [userId, report.id],
  )
  const planKey = useMemo(() => planStorageKey(userId, report.id), [userId, report.id])
  const [planState, setPlanState] = useState<PlanState>(() => readState(stateKey))
  /** 云端是否已对齐：对齐前不允许推送，避免「本机旧状态」把别的设备刚写的打卡覆盖掉。 */
  const syncedRef = useRef(false)
  const stateRef = useRef(planState)
  const pushTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    stateRef.current = planState
  }, [planState])

  // 换账号 / 换报告时切到对应的本地状态，并与云端对齐（云端空记录 = 首次上云，把本地推上去）。
  useEffect(() => {
    let cancelled = false
    syncedRef.current = false
    const local = readState(stateKey)
    setPlanState(local)
    void (async () => {
      try {
        const remote = await api.planState(report.id)
        if (cancelled) return
        const merged = mergePlanState(local, remote)
        writeState(stateKey, merged)
        setPlanState(merged)
        if (!samePlanState(merged, remote)) {
          await api.savePlanState(report.id, planPushPayload(merged))
        }
      } catch {
        // 离线 / 服务端不可用：本地照常打卡，下次改动会再推一次（不弹框、不阻塞页面）
      } finally {
        if (!cancelled) syncedRef.current = true
      }
    })()
    return () => {
      cancelled = true
    }
  }, [stateKey, report.id])

  // 离开页面时立刻补发还没到点的防抖推送（否则最后 1 秒内的勾选会丢）。
  useEffect(() => {
    const reportId = report.id
    return () => {
      if (pushTimer.current === null) return
      clearTimeout(pushTimer.current)
      pushTimer.current = null
      void api.savePlanState(reportId, planPushPayload(stateRef.current)).catch(() => {})
    }
  }, [report.id])

  const pushSoon = () => {
    if (!syncedRef.current) return
    if (pushTimer.current !== null) clearTimeout(pushTimer.current)
    pushTimer.current = setTimeout(() => {
      pushTimer.current = null
      void api.savePlanState(report.id, planPushPayload(stateRef.current)).catch(() => {})
    }, PUSH_DELAY_MS)
  }

  const minutes = planState.daily_minutes

  const plan = useMemo<StudyPlan>(() => {
    const stored = readPlan(planKey)
    if (stored !== null && stored.report_id === report.id && stored.daily_minutes === minutes) {
      return stored
    }
    // r51：报告页开启检索引用（纯函数、零网络），旧快照无该字段时下方零占位。
    return buildStudyPlan(report, { dailyMinutes: minutes, learned, citations: true })
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
    pushSoon()
  }

  const changeMinutes = (value: PlanMinutes) => {
    setPlanState((previous) => {
      const next: PlanState = { ...previous, daily_minutes: value }
      writeState(stateKey, next)
      return next
    })
    pushSoon()
  }

  /** r95：起始日与打卡走同一条写入路径（同一个 PlanState + 同一次防抖上推）。 */
  const setStartedOn = (value: string) => {
    setPlanState((previous) => {
      const next: PlanState = { ...previous, started_on: value }
      writeState(stateKey, next)
      return next
    })
    pushSoon()
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
  const today = isoDay(new Date())
  const pace = planPace(plan, planState.done, planState.started_on, today)
  const resumeTarget = pace.firstOpenDay === null ? null : resumeDay(pace.firstOpenDay, today)
  const paceText = !pace.started
    ? PLAN_IDLE_NOTICE
    : pace.expired
      ? `${PLAN_EXPIRED_NOTICE}（还有 ${pace.behindDays} 天没做完）`
      : pace.behindDays > 0
        ? `今天是第 ${pace.todayDay} 天 · 前面还有 ${pace.behindDays} 天没做完`
        : `今天是第 ${pace.todayDay} 天 · 进度没落下`

  return (
    <Card className="sc-coach-block">
      <div className="sc-coach-blockhead">
        <h3 className="sc-coach-blocktitle">7 天学习计划</h3>
        <p className="sc-coach-meta">{`已完成 ${stats.completed} / ${stats.total} 项 · ${stats.percent}%`}</p>
      </div>
      <p className="sc-coach-note">{PLAN_SYNCED_NOTICE}</p>

      <div className={pace.started ? 'sc-plan-pace' : 'sc-plan-pace is-idle'}>
        <span className="sc-plan-pace-text">{paceText}</span>
        {!pace.started ? (
          <button type="button" className="sc-plan-pace-btn" onClick={() => setStartedOn(today)}>
            今天开始
          </button>
        ) : pace.expired ? (
          <button type="button" className="sc-plan-pace-btn" onClick={() => setStartedOn(today)}>
            从今天重新排
          </button>
        ) : pace.behindDays > 0 && resumeTarget !== null ? (
          <button
            type="button"
            className="sc-plan-pace-btn"
            onClick={() => setStartedOn(resumeTarget)}
          >
            顺延到今天
          </button>
        ) : null}
      </div>

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
          const dayClass = [
            'sc-plan-day',
            dayDone ? 'is-done' : '',
            day.day === pace.todayDay ? 'is-today' : '',
          ]
            .filter((name) => name !== '')
            .join(' ')
          return (
            <li className={dayClass} key={day.day}>
              <div className="sc-plan-dayhead">
                <span className="sc-plan-daynum sc-mono">{`Day ${day.day}`}</span>
                {day.day === pace.todayDay ? (
                  <span className="sc-plan-daytoday">今天</span>
                ) : null}
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
                    {task.citations && task.citations.length > 0 ? (
                      <div className="sc-plan-taskmeta">
                        <span>依据：</span>
                        {task.citations.map((citation) => (
                          <Link
                            className="sc-plan-taskgo"
                            to={citation.href}
                            key={`${citation.chapter_id}:${citation.section_id}`}
                            title={citation.title}
                          >
                            {citation.title}
                          </Link>
                        ))}
                      </div>
                    ) : null}
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
