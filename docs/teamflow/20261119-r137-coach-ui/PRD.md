# r137：讲席页面展示升级

- 日期：2026-11-19
- 发起：用户反馈「讲席模块有点简陋啊」。
- 主题：**纯前端展示层升级**。API 契约、工具闭集、LangGraph 编排语义、轨迹落库口径零改动。

## 1. 问题定位

- `CoachPage` 自 r100 落地后没再做视觉打磨：原生 `<table>` 历史、裸 `<h2>/<p>` 结果、散落 inline `style={{ marginBottom }}`、单行动作区，和站内其他工具的卡片/侧栏/阶段反馈语言不一致。
- 前端 `TOOL_LABELS` 只列了 4 个工具，后端 `TOOL_CATALOG` 自 r108 起已有 5 个（缺 `read_leap_archive`），轨迹里该工具会以英文裸名出现。
- 用户看不到「它能读什么、边界在哪」，空白页也没有可点的示例提问，首次使用门槛偏高。

## 2. 改动

### 2.1 信息架构

- 桌面双栏：左侧「提问台 → 阶段反馈 → 结果 / 空态」，右侧 sticky「能力面板 + 编排历史」；≤1180px 侧栏落到主栏下方并两列并排，≤720px 单列。
- 提问台：`textarea`（200 字，与后端契约一致）+ 目标岗位输入 + `Button loading`；4 个示例问题一键填入；Ctrl/⌘+Enter 提交。
- 加载：`PhaseLoader` 四阶段按已用秒数分档（0–8s 规划 / 8–28s 执行 / 28–38s 反思 / 38s+ 结论），带 elapsed；后端不推进度，仍是粗粒度文案步进，不伪精确。
- 结果分层：结论高亮块 → 行动清单（CSS counter 编号）→ 引用（ref 令牌 + 站内链接）→ 可折叠「完整审计轨迹」。

### 2.2 轨迹时间线

- 新组件 `components/coach/CoachTrace.tsx`：按 `plan / tool / tool_skip / reflect / final` 渲染 01–04 编号节点；未知 kind 只显示标签与兜底文案。
- 节点内展示规划步骤、工具参数、返回条目（ref + 标题 + 摘要）、反思缺口与补跑、final 行动项与越界引用丢弃数；badge 区分「兜底计划 / 材料不足 / 未返回材料 / 丢弃引用」。
- 工具中文标签抽到 `lib/coachTools.ts`，前后端闭集对齐并补齐 `read_leap_archive`；从组件文件移出常量也避开了 react-refresh 的 only-export-components 告警。

### 2.3 侧栏

- 能力面板列 5 个只读工具及用途，明确「单轮 ≤3 步 / 全场 ≤2 轮 / 越界引用丢弃」。
- 历史由 `<table>` 改为可点卡片列表，当前回放项高亮；时间显示 `MM-DD HH:mm`。未新增删除端点（本轮不动后端契约）。

### 2.4 样式

- `base.css` **append-only** 新增 r137 段落；颜色/间距/字号全部走 tokens.css，未出现裸色值。
- 复用既有 `.sc-coach-kicker / .sc-coach-note / .sc-coach-meta`；新结果容器改名 `sc-coach-run-card`、行动区改名 `sc-coach-run-actions`，避开 r65 遗留的 `.sc-coach-result / .sc-coach-actions` 语义冲突。

## 3. 验证

- 前端 typecheck / lint / build 全绿；工程门禁 41/41（含裸色值与样式 append-only）。
- 全量 vitest 47 files / 577 tests passed（本机 EPERM 临时目录噪音仍在，非断言失败；CI 为准）。
- 系统 Python Playwright 1.64 + 路由 mock（1280×900 / 900×900）：示例问题 4、能力条目 5、历史条目 1、空态流程 4；桌面布局 `608px 320px` 且侧栏 `sticky`，窄屏 `852px` 单列；提交后轨迹节点 5、标签顺序「规划/执行/反思/执行/结论」、行动 2、引用 1、表格 0；badge 正确显示「材料不足」「丢弃越界引用 1 条」。

## 4. 未纳入本轮

- 编排历史的删除入口（后端无 DELETE，需扩契约 + 测试）。
- 服务端流式推送真实节点进度（当前仍按时间分档，与站内其他 AI 页面一致）。
- 太傅全局悬浮按钮在部分视口与右侧历史卡片视觉相邻，属全局组件，未在本次范围内调整。
