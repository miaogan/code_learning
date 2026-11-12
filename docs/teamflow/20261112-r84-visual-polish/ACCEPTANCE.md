# r84 视觉打磨 · 验收

背景：用户反馈「前端不够亮眼」。先对主要页面做了一轮 CDP 截图巡检（1280×900，全 mock），
按「修真 bug → 补信息密度 → 加观感」顺序做了四块。用户四项全选。

## §1 错误边界 + 空态引导卡

**巡检发现的真问题**：/report 只要一个 `ShortfallCard` 拿到缺字段的短板
（mock 缺 `courses`/`actions`/`evidence`），整页渲染成**全黑空页**——React 对未捕获
渲染错误会卸载整棵树。修法两层：

1. `components/ui/ErrorBoundary.tsx`（class 组件）：兜底卡 `sc-fault`（RENDER FAULT +
   粒度名 + 错误一句话 + 「重试本区 / 刷新页面」）。
   - **路由级**：`App.tsx` 用 `<ErrorBoundary key={pathname}>` 包住 `<Routes>`——
     key 按路由换，避免 A 页崩过一次后 B 页一直看到兜底卡；
   - **区块级**：`ReportPage` 短板列表单独包一层，一张脏卡不再连坐整份医案。
2. `EmptyState` 升级：可选 `hints`（1–3 条「现在能做什么」）与 `altLabel/altTo`（次级入口）；
   `.sc-empty` 撑到 min-height 280 并垂直居中，大空白变成引导卡。报告页/评鉴页空态接入。

## §2 数据可视化（不引图表库，全部 SVG/CSS + lib 纯函数）

- **打卡热力图**：`lib/heatCalendar.ts`（7 行×12 周、周一为首行、最右列止于今天；
  色阶 0–4 阈值集中在 `heatLevel`）→ `components/history/HeatCalendar.tsx` → 战绩页
  成绩走势上方；每格带 title 读数（颜色不单独承载信息）。
- **评鉴每日趋势柱**：`lib/eval.ts` 新增 `trendBars(rows, maxHeight)`（柱高=调用量归一、
  色阶 high ≥90% / mid ≥60% / low 其余）→ EvalPage 每日趋势表格上方柱状速览，表格保留精确读数。
- 已有组件不重复造：报告仪表环（RingProgress 112）、成绩折线（TrendChart）、首页技能刻度条均已存在。

## §3 顶栏 streak 徽章

`lib/streak.ts`（纯前端）：按本机时区日去重；**锚点规则**——今天没练但昨天练了，streak
保留（早晨打开不该显示 0）；周口径周一为始。`components/ui/StreakBadge.tsx`：
「连续 N 天 · 本周 x/7」+ 22px 迷你周进度环；取数失败或全 0 时**静默隐藏**（锦上添花
不值得报错，新用户顶栏不出现 0/7 的挫败感）。不动后端。

## §4 微动效

- 页面进场 stagger：`.sc-page > :nth-child(n)` 浮入（路由切换重挂自动重放）；
- 卡片 hover 抬升 1px：`.sc-lab-sf` / `.sc-course-card`（`@media (hover:hover)`）；
- 雷达值多边形入场：从中心收拢展开（`transform-box: fill-box`）；
- 分数环 dasharray/offset 加 transition（数值异步到达时平滑）；
- 全部动画在 `prefers-reduced-motion: reduce` 下关掉。

## 验证

- 纯函数测试（vitest，node 环境）：新增 `streak.test.ts`（9）、`heatCalendar.test.ts`（7）、
  `eval.test.ts` 增 `trendBars`（4）——全量 **40 文件 512 测试 0 失败**（`--maxWorkers=1`）；
- 浏览器断言 `check-visual-polish.cjs`（全 mock，7 组 PASS）：
  ①脏短板 → 区块级兜底卡，仪表区照常；②「重试本区」重挂仍稳定落在兜底卡；
  ③热力图 84 格 + 汇总「近 12 周 3 次 · 活跃 3 天」；④顶栏「连续 3 天 · 本周 3/7」+ 迷你环；
  ⑤评鉴 6 根趋势柱、最高柱 64px、标签正确；
- 截图巡检 `shots-tour.cjs`（12 张：9 页 + 太傅面板 + 手机首页，含各页现状底稿）；
- 回归：`check-sticky-nav` / `check-clear-jitter` / `check-two-replies` / `check-empty-state` 全 PASS；
- typecheck / lint 0 warning / build 通过（TEMP 指向工作区 `.tmpbuild`，绕宿主 fs shim）。

## 过程记录（环境坑，与代码无关）

1. 巡检时发现 dev server 全页白屏 + 模块 500：本轮早前为排查 build 误杀了 vite 的
   esbuild 常驻服务进程——**杀 esbuild.exe 会弄死 dev server**。重启时新 vite 又只绑
   `[::1]`，而 CDP 脚本全走 `127.0.0.1` → 必须用 `vite --host 127.0.0.1 --port 5173` 启动。
2. tour 首版 mock 的 `/api/timeline` 形状不对（TimelineSection 读 `runs.length`），
   路由级兜底卡接住了——顺带验证了 §1 的价值。
