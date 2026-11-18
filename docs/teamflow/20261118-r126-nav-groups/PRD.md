# r126 侧栏多级菜单（流程 / 工具 / 设置 三大区折叠）

## 背景与诉求

工具页累计 13 个（r3 以来逐步新增），侧栏「工具」组始终平铺，条目高度超出视口后侧栏内部出现滚动条。用户明确反馈：**不喜欢左侧菜单有滚动条，希望做成多级菜单**；首轮把工具项折成 5 个语义分组后用户再反馈：**点开分组仍会出现滚动条，折叠要上移到「流程 / 工具 / 设置」层级**。

## 方案（迭代四终态：流程常驻 + 工具/设置级联浮层）

用户反馈迭代三：**流程展开频繁（主路径每天用），每次都要 hover/点击太麻烦；工具和设置保留折叠即可**。终态：

- **「流程」不再折叠**——Stepper 竖排（自带「流程」组标题）直接常驻侧栏，日常主路径零操作直达；
- **「工具 / 设置」保留向右级联浮层折叠**（迭代三机制全部不变）：hover 停留 300ms / 点击后向右浮出面板（`--elev-2` + `--radius-8`，z-index 60——高于 topbar 10 / toast 20、低于 modal 80），工具面板内 5 个分组头再向右级联一层（文房=检索/讲席/修文、研习=学堂/演武/镜试、岗途=对岗/跃迁、雷达=先锋/国子监、卷藏=战绩/卷宗/校勘）；
- 侧栏常态高度 = 流程（标题 + 5 步）+ 工具头 + 设置头 ≈ 8 行，无滚动条；`.sc-sidebar-inner` 保持 `overflow: visible`（r83 兜底退役）；
- 触发规范维持迭代二/三口径：hover 停留 300ms 展开、移出 350ms 收起、同级互斥、点击保底且压过 hover、触屏门控；浮层专属三条规则不变（`activeInside` 只做高亮不强制展开、面板内点链接自动收起、pinned/hover 双通道互斥）。

`<1024` 顶部横向工具条**保持平铺**（平铺清单由分组推导，两处入口同源）；样式全部走 token（尺寸用 `calc(var(--sp-*) * n)` 组合，无裸值）。

## 改动清单

- `frontend/src/lib/navGroups.ts`（新增）：`TOOL_GROUPS` / `TOOL_ITEMS` / `isRouteActive`，分组与激活判定的唯一数据源。
- `frontend/src/components/ui/NavSection.tsx`（新增）：浮层分区组件——hover 停留展开（300ms/350ms、互斥、`(hover: hover) and (pointer: fine)` 门控）+ 点击保底（pinned 走 context 互斥、面板外点击收起、面板内点链接自动收起）；`NavSectionGroup` 提供同级双通道（openId / pinnedId）协调。
- `frontend/src/components/ui/ToolNav.tsx`：支持 `groups` prop（二级分组复用 NavSection/NavSectionGroup）与空 `label`（大区头已承担标题）；horizontal 平铺回退不变。
- `frontend/src/App.tsx`：侧栏 = 常驻 `Stepper`（竖排，自带「流程」标题）+ 两个 `NavSection` 浮层分区（工具 / 设置），包在 `NavSectionGroup` 内；删除内联 `TOOL_ITEMS`，改 import。
- `frontend/src/styles/base.css`：`.sc-navsection`（relative 锚点）/ `.sc-navsection-body`（absolute 向右浮出，二级再级联）、大区头样式、`.sc-sidebar-inner` 放开 overflow（r83 兜底退役）；全部走 token，无裸值。
- `frontend/src/test/navGroups.test.ts`（新增）：分组唯一性 / 平铺同源 / 路由契约 / `isRouteActive` 前缀粘边与首页全等共 8 例（hover 延迟与互斥属组件行为，仓库无 testing-library，靠 CI 手测覆盖）。

## 验收

- `npx tsc --noEmit`、`npm run lint`（0 warning）、`npm test`（全部通过）、`npm run build` 全绿。
- 本机 vitest 存在已知环境噪音：archive/practice/profileRadar/tutorials 四个文件偶发被 SSR Temp EPERM 整文件跳过（沙箱拦 `C:\Users\user\AppData\Local\Temp`，与 esbuild 构建同源），多次运行总数在 516–536 间波动，CI/Linux 不受影响。
- 侧栏收起态：三个大区头 + 区间留白，高度不足 80px；展开任意大区也不会超过一屏。

## 边界

- 「流程」常驻展开（迭代四调整，用户明确要求）；「工具 / 设置」折叠浮层。
- 不改任何页面路由与 `to` 值；纯导航组织形式变化。
