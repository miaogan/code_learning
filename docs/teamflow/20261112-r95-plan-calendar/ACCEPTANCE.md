# r95 学习计划按日历推进 · 验收

## §1 交付内容

**契约（两侧同步）**

- `PlanStatePayload` / `PlanState` 新增 `started_on: str`（本机日历日 `YYYY-MM-DD`，空串＝未开始）：
  `backend/app/schemas.py` 与 `frontend/src/api/types.ts` 逐字对齐。
- 存储：`plan_states` 新增列 `started_on TEXT NOT NULL DEFAULT ''`（`core/db.py` 的 `R61_SCHEMA` 建新库、
  `_R61_ADDED_COLUMNS` + `_ensure_r61_columns()` 给存量库补列，`init_db()` 第 12.1 步，幂等）。
- 净化：`services/learn.py::clean_date()` 只认**真实存在的** `YYYY-MM-DD`（`2026-02-31` 落空串），
  与 id 净化同口径**静默夹取不报错**——该字段由后台自动同步写，用户没有重试入口。

**排程（纯函数，`lib/studyPlan.ts`）**

| 函数 | 职责 |
|---|---|
| `isoDay(date)` | 本机日历日；不用 `toISOString()`（UTC 会让东八区凌晨差一天） |
| `isPlanDay(iso)` | 形态 + 日历双重校验（`Date.UTC` 回读比对，拒 `2026-02-31`） |
| `dayOffset(from, to)` | 整天差，按 y/m/d 用 UTC 归一，避开夏令时 |
| `shiftDay(iso, days)` | 前后挪天，跨月跨年正确 |
| `planPace(plan, done, startedOn, today)` | 今天对应哪个 Day / 是否过期 / 落后几天 / 第一个没做完的天 |
| `resumeDay(firstOpenDay, today)` | 顺延：把第一个没做完的天挪到今天 |

`planPace` 的三条判定口径：

1. **未开始**（无起始日）：`todayDay = null`、`behindDays = 0`——还没承诺哪天做，不算落后；
2. **进行中**：`todayDay = clamp(offset + 1, 1, 7)`；`behindDays` 只数**今天之前**没做完的天
   （今天还有时间，不算落后）；
3. **过期**（`offset ≥ 7`）：`todayDay = null`、`expired = true`，7 天全部按过去算——
   不假装「今天还是第 7 天」，否则用户会永远看到一个假的今天。

**界面（`components/report/WeekPlan.tsx`）**

- 说明行下新增 `.sc-plan-pace`：一句状态（未开始 / 今天是第 N 天 / 已然落后 / 已过期）+ 一个按钮
  （今天开始 / 顺延到今天 / 从今天重新排）；
- 当天卡片加 `is-today` 描边与「今天」小标；已完成态仍走 `is-done` 绿边（`is-today:not(.is-done)`）；
- `PLAN_SYNCED_NOTICE` 补「起始日」；新增 `PLAN_IDLE_NOTICE` / `PLAN_EXPIRED_NOTICE` 两个常量；
- 起始日与打卡共用同一个 `PlanState` 与同一套防抖上推（`setStartedOn`），不存在第二种写语义。

**样式**：`base.css` 只加 `.sc-plan-pace*` / `.sc-plan-day.is-today` / `.sc-plan-daytoday`，
全部取既有 token，零裸色值裸尺寸；窄屏靠 `flex-wrap` 自动换行。

## §2 验证

| 检查 | 结果 |
|---|---|
| 后端 `tests/test_r61_learn_sync.py` | 28 passed（+9：`clean_date` 9 组参数化、起始日回写、脏值静默、无关写入不抹起始日） |
| 后端全量 `pytest -q` | 进度线 100% 无 F（收尾汇总被宿主 safe-delete hook 吞掉、exit 1，同 r93 已知环境问题） |
| 后端 `ruff check app tests` | All checks passed |
| 前端 `src/test/studyPlan.test.ts` | 35 passed（+11：日历工具 3、pace 6、跨设备 3；`planPushPayload` 断言补 `started_on`） |
| 前端全量 `npm test` | 41 files / 542 tests passed |
| `npm run typecheck` / `npm run lint` / `npm run build` | 全过（lint `--max-warnings 0`；build 314 modules） |

## §3 兼容与风险

- **老客户端 / 老记录**：`started_on` 缺键按空串处理（未开始），不会把已有打卡清掉；
  读路径对坏日期同样落空串，所以「存量打卡 + 无起始日」的用户看到的是「今天开始」，点一下即对齐。
- **时钟回拨 / 跨时区**：起始日在未来时按第 1 天处理；日历日只比 y/m/d，不涉及时分秒。
- **跨零点**：`today` 在渲染时计算，页面整夜挂着不会自己跨天（下一次交互/刷新即更新）——
  当前不引入定时器，避免后台标签页空转。
- **未做**：推送提醒、日历订阅、静默自动顺延（见 PRD §3）。
- **视觉未实机走查**：本轮为纯逻辑 + 小面积样式改动，未做 390px 真机截图核对（并入真实环境补测清单）。
