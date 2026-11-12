# r96 首页「今日计划」· 验收

## §1 交付内容

**纯函数（`frontend/src/lib/studyPlan.ts`）**

- `todayPlan(plan, done, startedOn, today) → TodayPlanView`：首页唯一判定口，五种 `status`
  （`none` / `idle` / `active` / `done` / `expired`），输出今天对应 Day、今天的任务、还剩几项、
  「接着做」指向的任务、全计划未完成天数。
- 内部**复用 `planPace`**（r95），所以「今天第几天 / 是否过期」在首页与报告页必然同源：
  未开始不给假 Day 1，过期也不给假第 7 天。
- `nextTask` 口径分两种：今天是「今天第一条没做完的」；未开始 / 已过期是「全计划第一条没做完的」
  （这两种状态下用户要的是「从哪开始」，不是「今天第几项」）。

**组件（`frontend/src/components/report/TodayPlan.tsx`）**

- 自己取数：`GET /api/reports/latest` → `GET /api/plans/{report_id}`，阅读进度走 `useLearnProgress()`；
- 两个请求都经本地 `optional()` 包裹，任一失败即当作「没有」，**整块不渲染**——首页是入口页，
  不该因为一次读失败弹错误条或挡住上传流程；
- 只读：任务行是 `Link`，按钮是「接着做」/「去医案…」，**没有任何写入**；
- 计划用 `buildStudyPlan(report, { dailyMinutes, learned })` 现算，不开 `citations`
  （检索引用只在报告页生成，首页保持轻）。

**接入**：`UploadPage` 在「已有画像 · 回访」条下方渲染，条件与回访条一致
（`phase === 'idle' && saved !== null`）——新用户首页不受影响。

**样式**：`base.css` 新增 `.sc-today*` 段，只用既有 token；左边 2px accent 竖线延续回访条的视觉语言，
`margin-top: var(--sp-5)` 与下方 `.sc-lab-panel` 的 `sp-6` 间距错开一级；窄屏靠 `flex-wrap` + 任务标题
`ellipsis` 收敛，不产生横向滚动。

## §2 验证

| 检查 | 结果 |
|---|---|
| `src/test/studyPlan.test.ts` | 40 passed（+5：none / idle / active / done / expired 五态） |
| 前端全量 `npm test` | 41 files / 547 tests passed |
| `npm run typecheck` / `npm run lint` | 过（lint `--max-warnings 0`） |
| `npm run build` | 过（314 modules） |
| 后端 | 零改动（复用既有只读接口） |

## §3 兼容与风险

- **额外请求**：首页对有画像的用户多发 2 个 GET（latest report + plan state）；无报告用户会吃一个
  404（被 `optional` 吞掉）。与归档页同一套取数口径，未新增接口。
- **与报告页的差异**：首页计划不开 `citations`、不做快照缓存，任务顺序仍由同一确定性排程与阅读进度决定，
  不会与报告页的任务集合冲突（打卡按 `task.id`）。
- **未做**：首页打卡、通知、跨零点自动刷新（与 r95 同一条取舍：不引定时器空转）。
- **视觉未实机走查**：本轮为新增卡片 + 纯 token 样式，未做 1280 / 390 截图核对，并入真实环境补测清单。
