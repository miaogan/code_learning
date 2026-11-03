# 移动端可用性修复：顶部导航与触控目标（r21）

> 性质：DESIGN 层的尺寸变更 + 一处**功能缺失**修复。桌面规则一字未改。
> 触发场景：手机（鸿蒙 7.x，390×844）经内网穿透访问自用实例。
> 基线文档：[DESIGN（r1）](../../20261031-r1-dev-skill-coach/DESIGN.md) §1.2「<1024 顶部横向步骤条（高 40，5 个点 + 连接线 2px）」。

## 1. 实测到的两个问题（390×844 视口，真实数据）

| # | 现象 | 证据 |
| --- | --- | --- |
| A | **手机上没有任何入口进入「练习 / 成绩趋势 / 简历润色」** | `.sc-sidebar { display: none }` 在 <1024 生效，而 `ToolNav` 只渲染在侧栏内（`App.tsx` 仅侧栏一处）。`ToolNav` 组件本身早已支持 `orientation="horizontal"`（源码注释写明「<1024 收起侧栏后的顶部 40 高工具条」），但从未接线 |
| B | 顶部步骤条退化为 **5 个无字圆点**，每项仅 **16px 高** | `.sc-stepper.is-horizontal .sc-step-label` 用 `clip-path: inset(50%)` 隐藏文字；`.sc-step` 高 16（dot 16 + padding-y 0） |

A 是功能缺失，比 B 严重：手机上最常用的「刷题」在流程 5 步之外，没有入口就等于打不开。

## 2. 改动

| 文件 | 改动 |
| --- | --- |
| `App.tsx` | `.sc-topstepper` 内新增 `<ToolNav items={TOOL_ITEMS} orientation="horizontal" />`（复用同一份 `TOOL_ITEMS`，不造第二份数据） |
| `tokens.css` | 新增 `--touch-min: 44px`（append-only 独立 `:root` 块，不改任何既有 token） |
| `base.css` | 文件末尾追加 `@media (max-width: 1023px)` 段：顶部条改为横向滚动容器；两类导航项 44 高；恢复步骤文字 |

### 2.1 尺寸推导

- `--touch-min = 44px`：Apple HIG 最小触控 44pt、Material 48dp 的下限口径。取 44 而非 48，是因为 390 宽下 8 个导航项横向排布，48 会让单屏可见项更少。
- 顶部条总高 **53 = 44（项）+ padding-y 4×2（`--sp-1`）+ 底边线 1**。
- 导航项宽 **104 = dot 16 + gap 8（`--sp-2`）+ 4 字标签 56 + padding-x 12×2（`--sp-3`）**。
- 横向内容宽 **852 ≈ 5 步骤 × 104 + 3 工具项 + 组标题 + gap**，超出 390 ⇒ 必须滚动；实测 `scrollWidth 852 / clientWidth 390`，`overflow-x: auto` 生效，整页 `scrollWidth` 仍为 390（无页面级横滚）。

### 2.2 刻意未改的两处（附理由）

| 目标 | 现值 | 为何不改 |
| --- | --- | --- |
| 主按钮 `--btn-h` | 40px | 它被 `--iq-composer-h = 156`（= padding 12×2 + 输入框 84 + gap 8 + 按钮行 40）等**固定高推导**引用；在移动断点把 `--btn-h` 抬到 44 会让实际内容高 160 > 156，粘性输入区被裁。要改必须重算整条 composer 链条，属独立需求 |
| 筛选 chip `--chip-h` | 24px（实测渲染 32） | 练习页筛选区单屏最多 24+ 个 chip，抬到 44 会把筛选区撑成数屏、反而更难用；36–40 才是合理折中，需真机确认后再定 |

## 3. 验证结果（390×844 实测，注入新 CSS 后测量）

| 指标 | 改动前 | 改动后 |
| --- | --- | --- |
| 步骤项高度 | 16 | **44**（5 项全部） |
| 步骤文字可见 | 否（`clip-path` 隐藏） | **是**（5 项全部 `labelVisible: true`） |
| 工具项高度 | 不存在 | **44**（3 项） |
| 顶部条可横滑 | — | `scrollWidth 852 / clientWidth 390` |
| 页面级横向溢出 | 无 | **仍无**（`scrollWidth 390`） |

另：`npm run typecheck` 通过；`npm run lint` 0 error / 28 warning（等于既有基线 `--max-warnings 28`，未新增）。

## 4. 待真机确认

1. 横向滑动的**可发现性**：8 项只露出前 3–4 项，用户是否意识到右侧还有内容（必要时加渐隐遮罩或首屏自动滚到当前步）。
2. 筛选 chip 与主按钮的触控尺寸（见 §2.2），按真机手感决定是否另开需求重算 composer 链条。
3. 鸿蒙 ArkWeb 对 `overscroll-behavior-x: contain` 与 `scrollbar-width: none` 的支持（若失效只是滚动条仍可见，不影响可用）。

## 5. 回滚

删掉 `base.css` 末尾的 r21 `@media` 段、`tokens.css` 的 `--touch-min` 块、`App.tsx` 顶部那行 `ToolNav` 即可回到 r20 基线行为（会重新失去手机上三个工具页入口）。
