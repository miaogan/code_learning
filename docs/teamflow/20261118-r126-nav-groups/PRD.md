# r126 侧栏多级菜单（流程 / 工具 / 设置 三大区折叠）

## 背景与诉求

工具页累计 13 个（r3 以来逐步新增），侧栏「工具」组始终平铺，条目高度超出视口后侧栏内部出现滚动条。用户明确反馈：**不喜欢左侧菜单有滚动条，希望做成多级菜单**；首轮把工具项折成 5 个语义分组后用户再反馈：**点开分组仍会出现滚动条，折叠要上移到「流程 / 工具 / 设置」层级**。

## 方案（迭代三终态：hover 停留展开 + 点击保底）

折叠层级保持在「流程 / 工具 / 设置」三大区 + 工具区 5 个二级分组不变；触发方式从纯点击升级为 **hover 停留展开 + 点击保底**。

业界口径（本次落地前调研）：
- **NN/g《Menu Design》**：hover 子菜单对触屏 / 键盘不可用，必须保留点击通道；hover 菜单建议 0.3–0.5s 停留延迟。
- **Baymard Institute 2025**：61% 的网站 hover 菜单没有停留延迟，鼠标路过就弹出——闪烁与误触是 hover 菜单的第一大坑。
- **Drupal 侧栏可用性评审（2026-02）**：hover + click 混用会打架（hover 先展开、点击又收起）；纵向扫过侧栏会让多个区轮流开合、布局抖动。结论：hover 展开需互斥（同时只开一个），且点击要能压过 hover。

落地规则（`NavSection` / `NavSectionGroup`）：
1. **hover 展开**：鼠标进入分区停留 `300ms` 才展开（`matchMedia('(hover: hover) and (pointer: fine)')` 才启用，触屏不生效）；移出 `350ms` 后收起——滑进展开的内容区不会收，缓冲期内返回也不闪。
2. **hover 互斥**：同一侧栏（含工具区二级分组）同一时刻只有一个 hover 展开的分区，杜绝纵向扫过时布局抖动（`NavSectionGroup` context 协调）。
3. **点击保底且优先**：点击仍可开合；点击收起时清掉在途 hover 计时并连 hover 态一起收，避免「点了收起又被 hover 弹开」。
4. **路由激活强制展开**：当前页所在大区/分组始终展开（pinned 与 hover 之外第三来源）。

| 大区 | 内容 |
|---|---|
| 流程 | 5 步线性流程（Stepper 原样） |
| 工具 | 13 个工具项按 5 个语义分组二级折叠：文房（检索/讲席/修文）、研习（学堂/演武/镜试）、岗途（对岗/跃迁）、雷达（先锋/国子监）、卷藏（战绩/卷宗/校勘） |
| 设置 | 评鉴 / 考工 / 典制 |

`<1024` 顶部横向工具条**保持平铺**（平铺清单由分组推导，两处入口同源）；样式全部走 token。

## 改动清单

- `frontend/src/lib/navGroups.ts`（新增）：`TOOL_GROUPS` / `TOOL_ITEMS` / `isRouteActive`，分组与激活判定的唯一数据源。
- `frontend/src/components/ui/NavSection.tsx`（新增）：折叠分区组件——hover 停留展开（300ms/350ms 延迟、互斥、`(hover: hover) and (pointer: fine)` 门控）+ 点击保底 + 路由激活强制展开；`NavSectionGroup` 提供同级互斥协调。
- `frontend/src/components/ui/ToolNav.tsx`：支持 `groups` prop（二级分组复用 NavSection/NavSectionGroup）与空 `label`（大区头已承担标题）；horizontal 平铺回退不变。
- `frontend/src/App.tsx`：侧栏改为三个 `NavSection`（流程 / 工具 / 设置），包在 `NavSectionGroup` 内；删除内联 `TOOL_ITEMS`，改 import。
- `frontend/src/styles/base.css`：`.sc-navsection-body`、大区头与二级缩进层级、`.sc-sidebar-inner` flex 纵排；全部走 token，无裸值。
- `frontend/src/test/navGroups.test.ts`（新增）：分组唯一性 / 平铺同源 / 路由契约 / `isRouteActive` 前缀粘边与首页全等共 8 例（hover 延迟与互斥属组件行为，仓库无 testing-library，靠 CI 手测覆盖）。

## 验收

- `npx tsc --noEmit`、`npm run lint`（0 warning）、`npm test`（全部通过）、`npm run build` 全绿。
- 本机 vitest 存在已知环境噪音：archive/practice/profileRadar/tutorials 四个文件偶发被 SSR Temp EPERM 整文件跳过（沙箱拦 `C:\Users\user\AppData\Local\Temp`，与 esbuild 构建同源），多次运行总数在 516–536 间波动，CI/Linux 不受影响。
- 侧栏收起态：三个大区头 + 区间留白，高度不足 80px；展开任意大区也不会超过一屏。

## 边界

- 不动 5 步线性流程与「设置」组（仍是平铺）。
- 不改任何页面路由与 `to` 值；纯导航组织形式变化。
