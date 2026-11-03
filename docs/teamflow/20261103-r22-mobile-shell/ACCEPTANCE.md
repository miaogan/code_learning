# 验收报告 · r22 移动端外壳收口

## 1. 判据

| # | 判据 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | `<1024` 顶部导航吸顶，长页滚动后仍可见 | 通过（静态） | `base.css` r21 段内 `position: sticky; top: calc(var(--topbar-h) + env(safe-area-inset-top)); z-index: 9` |
| 2 | 顶部导航横滑能力不回退 | 通过 | sticky 元素的 `overflow-x: auto` 保留，r21 的 `flex:none` 与 44 高规则未动 |
| 3 | ≤640 时间线正文不再被 120 时间列挤压 | 通过（静态） | 新段 `grid-template-areas: 'time toggle' / 'main main'` |
| 4 | 移动端时间线不再出现内层滚动 | 通过 | `.sc-tl-scroll/.sc-tl-list` 置 `max-height:none; overflow-y:visible; overscroll-behavior:auto` |
| 5 | 移动端短页面不再因地址栏伸缩多出滚动 | 通过（静态） | `.sc-shell` 追加 `min-height: calc(100dvh - …)` 回退链 |
| 6 | iOS 聚焦输入框不再自动放大 | 通过（静态） | `<1024` 段 `textarea/input` 取 `--fs-input-mobile: 16px` |
| 7 | 刘海/手势条安全区生效且桌面无变化 | 通过（静态） | viewport `viewport-fit=cover`；顶栏与 composer 两处 `env()`，`env=0` 时尺寸等于 r21 |
| 8 | 桌面布局与既有固定高推导零变化 | 通过 | 所有新增规则位于 `<1024` / `≤640` / `env()`；`--btn-h`、`--chip-h`、`--iq-composer-h` 未改 |

## 2. 架构一致性

- 未改 HTTP 契约（`schemas.py` / `types.ts` 零改动），未改后端。
- 样式只用 token 与既有变量；新增唯一常量 `--fs-input-mobile` 走 append-only 块。
- 未引入新依赖、未改构建配置。

## 3. 复跑命令与结果（2026-11-03）

| 命令 | 结果 |
| --- | --- |
| `npm run typecheck` | 通过 |
| `npm run lint` | 0 error / 28 warning（等于既有基线，未新增） |
| `npm test -- --run` | 10 文件 / 136 passed |
| `npm run build` | 101 modules，dist 产出正常 |

## 4. 偏离与未覆盖（P3，不阻断）

- **P3-a 未做 390×844 浏览器复测**：Docker 前端在 r21 Basic Auth 之后，静态审查结论未在真实视口验证；吸顶高度、时间线两行网格、安全区均待真机确认。
- **P3-b 安全区只覆盖顶栏与面试 composer**：页面主体底部未加 `env(safe-area-inset-bottom)`，若后续做 PWA/全屏再议。
- **P3-c 顶部栏「本地存储」文案未加省略**：目标机型 390 不触发，320 宽或系统大字号下可能换行。
- **P3-d 触控目标仍 <44**：主按钮 40、chip 24/32（r21 §2.2 已说明牵动 composer 链条，须独立需求）。

## 5. 判定

✅ 通过（8 条判据全部满足；P3 为真机补测项，不阻断）。
