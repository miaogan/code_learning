# r126 侧栏多级菜单（流程 / 工具 / 设置 三大区折叠）

## 背景与诉求

工具页累计 13 个（r3 以来逐步新增），侧栏「工具」组始终平铺，条目高度超出视口后侧栏内部出现滚动条。用户明确反馈：**不喜欢左侧菜单有滚动条，希望做成多级菜单**；首轮把工具项折成 5 个语义分组后用户再反馈：**点开分组仍会出现滚动条，折叠要上移到「流程 / 工具 / 设置」层级**。

## 方案（迭代三终态：向右级联浮层）

折叠层级保持「流程 / 工具 / 设置」三大区 + 工具区 5 个二级分组不变；呈现方式从**下推手风琴**升级为**向右级联浮层**（类 Windows 开始菜单 / 管理后台多级浮出导航）：

- 大区头常驻侧栏（仅三行），hover 停留 / 点击后向右浮出面板（`position: absolute; left: calc(100% + sp-2)`，`--elev-2` 阴影 + `--radius-8`，z-index 60——高于 topbar 10 / toast 20、低于 modal 80，沿用既有裸值约定）；
- 工具面板内的 5 个分组头再向右级联一层（嵌套 `.sc-navsection` 天然锚到各自头部），形成「侧栏 → 面板 → 子面板」的层次；
- 浮层不挤占布局，侧栏任何状态下都无滚动条；
- `.sc-sidebar-inner` 的 `overflow-y: auto`（r83 内部自滚兜底）会裁掉浮层——侧栏内容收敛为三行后兜底不再需要，本块放开为 `overflow: visible`。

触发规范（迭代二调研结论，维持不变）：hover 停留 300ms 展开、移出 350ms 收起（面板是 wrapper 的 DOM 子节点，滑进面板不触发离开）、同级互斥；点击保底且压过 hover；触屏经 `(hover: hover) and (pointer: fine)` 门控。新增三条浮层专属规则：

1. **`activeInside` 不再强制展开面板**——浮层盖在主区上方，常开会挡内容；「当前位置」改由大区头高亮 + 面板内条目高亮承载；
2. **点击面板内链接跳转后自动收起**（面板 onClick 捕获 `<a>`）；
3. **pinned 与 hover 都互斥**（`NavSectionGroup` 双通道协调：`openId` / `pinnedId`）——点击面板外收起 pinned 浮层，杜绝两个浮层叠加。

| 大区 | 面板内容 |
|---|---|
| 流程 | 5 步线性流程（Stepper 原样） |
| 工具 | 5 个分组头级联出二级面板：文房（检索/讲席/修文）、研习（学堂/演武/镜试）、岗途（对岗/跃迁）、雷达（先锋/国子监）、卷藏（战绩/卷宗/校勘） |
| 设置 | 评鉴 / 考工 / 典制 |

`<1024` 顶部横向工具条**保持平铺**（平铺清单由分组推导，两处入口同源）；样式全部走 token（尺寸用 `calc(var(--sp-*) * n)` 组合，无裸值）。

## 改动清单

- `frontend/src/lib/navGroups.ts`（新增）：`TOOL_GROUPS` / `TOOL_ITEMS` / `isRouteActive`，分组与激活判定的唯一数据源。
- `frontend/src/components/ui/NavSection.tsx`（新增）：浮层分区组件——hover 停留展开（300ms/350ms、互斥、`(hover: hover) and (pointer: fine)` 门控）+ 点击保底（pinned 走 context 互斥、面板外点击收起、面板内点链接自动收起）；`NavSectionGroup` 提供同级双通道（openId / pinnedId）协调。
- `frontend/src/components/ui/ToolNav.tsx`：支持 `groups` prop（二级分组复用 NavSection/NavSectionGroup）与空 `label`（大区头已承担标题）；horizontal 平铺回退不变。
- `frontend/src/App.tsx`：侧栏改为三个 `NavSection`（流程 / 工具 / 设置），包在 `NavSectionGroup` 内；删除内联 `TOOL_ITEMS`，改 import。
- `frontend/src/styles/base.css`：`.sc-navsection`（relative 锚点）/ `.sc-navsection-body`（absolute 向右浮出，二级再级联）、大区头样式、`.sc-sidebar-inner` 放开 overflow（r83 兜底退役）；全部走 token，无裸值。
- `frontend/src/test/navGroups.test.ts`（新增）：分组唯一性 / 平铺同源 / 路由契约 / `isRouteActive` 前缀粘边与首页全等共 8 例（hover 延迟与互斥属组件行为，仓库无 testing-library，靠 CI 手测覆盖）。

## 验收

- `npx tsc --noEmit`、`npm run lint`（0 warning）、`npm test`（全部通过）、`npm run build` 全绿。
- 本机 vitest 存在已知环境噪音：archive/practice/profileRadar/tutorials 四个文件偶发被 SSR Temp EPERM 整文件跳过（沙箱拦 `C:\Users\user\AppData\Local\Temp`，与 esbuild 构建同源），多次运行总数在 516–536 间波动，CI/Linux 不受影响。
- 侧栏收起态：三个大区头 + 区间留白，高度不足 80px；展开任意大区也不会超过一屏。

## 边界

- 不动 5 步线性流程与「设置」组（仍是平铺）。
- 不改任何页面路由与 `to` 值；纯导航组织形式变化。
