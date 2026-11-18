# r126 侧栏多级菜单（工具组折叠）

## 背景与诉求

工具页累计 13 个（r3 以来逐步新增），侧栏「工具」组始终平铺，条目高度超出视口后侧栏内部出现滚动条。用户明确反馈：**不喜欢左侧菜单有滚动条，希望做成多级菜单**。

## 方案

把 13 个工具项折成 5 个语义分组（`lib/navGroups.ts` 唯一数据源），侧栏只显示组头，点开才见条目：

| 分组 | 条目 | 语义 |
|---|---|---|
| 文房 | 检索 / 讲席 / 修文 | AI 辅助工具 |
| 研习 | 学堂 / 演武 / 镜试 | 学习与练习 |
| 岗途 | 对岗 / 跃迁 | 岗位闭环 |
| 雷达 | 先锋 / 国子监 | 采集看板（技术雷达 / 岗位采集） |
| 卷藏 | 战绩 / 卷宗 / 校勘 | 记录存档 |

行为规则：
- **默认收起**；当前路由落在组内时该组**自动展开**（渲染期由 `pathname` 推导，刷新/切页即正确）。
- 手动展开/收起是组件内临时 state（会话级，不进 localStorage——组序由代码定死，记忆展开态价值低）。
- `<1024` 的顶部横向工具条**保持平铺**（40 高横条上折叠无意义；平铺清单由分组推导，两处入口同源）。
- 组头带 `aria-expanded` / `aria-controls`；子项沿用 `.sc-toolnav-item` 的当前态样式（accent 竖条 + tint 底）。

## 改动清单

- `frontend/src/lib/navGroups.ts`（新增）：`TOOL_GROUPS` / `TOOL_ITEMS`，分组唯一数据源。
- `frontend/src/components/ui/ToolNav.tsx`：支持 `groups` prop，`CollapsibleGroup` 折叠子组件；horizontal 平铺回退不变。
- `frontend/src/App.tsx`：删除内联 `TOOL_ITEMS`，改 import；侧栏传 `groups`。
- `frontend/src/styles/base.css`：`.sc-toolnav-group` / `.sc-toolnav-chevron` / `.sc-toolnav-group-body`，全部走 token（`--lh-small` / `--fs-small` / `--overlay-04` 等），无裸值。
- `frontend/src/test/navGroups.test.ts`（新增）：分组唯一性 / 平铺同源 / 路由契约 / 镜试入口 5 例。

## 验收

- `npx tsc --noEmit`、`npm run lint`（0 warning）、`npm test`（全部通过）、`npm run build` 全绿。
- 本机 vitest 存在已知环境噪音：archive/practice/profileRadar/tutorials 四个文件偶发被 SSR Temp EPERM 整文件跳过（沙箱拦 `C:\Users\user\AppData\Local\Temp`，与 esbuild 构建同源），多次运行总数在 528–536 间波动，CI/Linux 不受影响。
- 侧栏收起态高度：5 步骤 + 5 组头 + 设置组 3 项 ≈ 13 行，回到 r83 收紧后的「不滚动」目标。

## 边界

- 不动 5 步线性流程与「设置」组（仍是平铺）。
- 不改任何页面路由与 `to` 值；纯导航组织形式变化。
