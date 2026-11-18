# r126 侧栏多级菜单（流程 / 工具 / 设置 三大区折叠）

## 背景与诉求

工具页累计 13 个（r3 以来逐步新增），侧栏「工具」组始终平铺，条目高度超出视口后侧栏内部出现滚动条。用户明确反馈：**不喜欢左侧菜单有滚动条，希望做成多级菜单**；首轮把工具项折成 5 个语义分组后用户再反馈：**点开分组仍会出现滚动条，折叠要上移到「流程 / 工具 / 设置」层级**。

## 方案（迭代后终态）

侧栏折叠上移到顶层：只剩「流程 / 工具 / 设置」三个可折叠大区（`NavSection`），默认全部收起，当前路由所在大区自动展开。

| 大区 | 内容 |
|---|---|
| 流程 | 5 步线性流程（Stepper 原样） |
| 工具 | 13 个工具项按 5 个语义分组二级折叠：文房（检索/讲席/修文）、研习（学堂/演武/镜试）、岗途（对岗/跃迁）、雷达（先锋/国子监）、卷藏（战绩/卷宗/校勘） |
| 设置 | 评鉴 / 考工 / 典制 |

任意时刻展开的大区 ≤ 1 个、区内行数固定，侧栏永远不出滚动条：
- 大区头 = `.sc-toolnav-group` 样式的折叠按钮（`aria-expanded` / `aria-controls`）；
- 「工具」大区内部保留二级分组折叠（`ToolNav groups` 复用 `NavSection`），展开工具区只见 5 个组头；
- 展开判定与分组同口径：当前路由在区内强制展开，手动开合是会话级 state（不进 localStorage）；
- `<1024` 顶部横向工具条**保持平铺**（平铺清单由分组推导，两处入口同源）；
- 二级内容整体缩进一层（组头 `--sp-3 + --sp-4`、条目再加 `--sp-2`），层级一眼可辨；样式全部走 token。

## 改动清单

- `frontend/src/lib/navGroups.ts`（新增）：`TOOL_GROUPS` / `TOOL_ITEMS` / `isRouteActive`，分组与激活判定的唯一数据源。
- `frontend/src/components/ui/NavSection.tsx`（新增）：顶层折叠分区组件（流程 / 工具 / 设置共用，二级分组复用同一实现）。
- `frontend/src/components/ui/ToolNav.tsx`：支持 `groups` prop（二级分组复用 NavSection）与空 `label`（大区头已承担标题）；horizontal 平铺回退不变。
- `frontend/src/App.tsx`：侧栏改为三个 `NavSection`（流程 / 工具 / 设置）；删除内联 `TOOL_ITEMS`，改 import。
- `frontend/src/styles/base.css`：`.sc-navsection-body`、大区头与二级缩进层级、`.sc-sidebar-inner` flex 纵排；全部走 token，无裸值。
- `frontend/src/test/navGroups.test.ts`（新增）：分组唯一性 / 平铺同源 / 路由契约 / `isRouteActive` 前缀粘边与首页全等共 8 例。

## 验收

- `npx tsc --noEmit`、`npm run lint`（0 warning）、`npm test`（全部通过）、`npm run build` 全绿。
- 本机 vitest 存在已知环境噪音：archive/practice/profileRadar/tutorials 四个文件偶发被 SSR Temp EPERM 整文件跳过（沙箱拦 `C:\Users\user\AppData\Local\Temp`，与 esbuild 构建同源），多次运行总数在 516–536 间波动，CI/Linux 不受影响。
- 侧栏收起态：三个大区头 + 区间留白，高度不足 80px；展开任意大区也不会超过一屏。

## 边界

- 不动 5 步线性流程与「设置」组（仍是平铺）。
- 不改任何页面路由与 `to` 值；纯导航组织形式变化。
