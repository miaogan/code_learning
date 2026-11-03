# 移动端外壳收口（r22）

> 性质：单点适配修复，**桌面（≥1024）规则零语义变化**（只把 `100vh` 换成带 `dvh` 的回退链）。
> 触发：r21 之后对 390×844 移动端做静态审查，确认 5 项遗留（导航不吸顶 / 时间线窄屏挤压 / `100vh` / 输入框 14px / 无安全区）。
> 前置：r21 已修「工具页无入口」「步骤条无文字」两项，本需求不重复处理。

## 1. 改动面

| 文件 | 改动 |
| --- | --- |
| `frontend/src/index.html` | viewport 追加 `viewport-fit=cover`（否则 `env(safe-area-inset-*)` 恒为 0，安全区规则等于没写） |
| `frontend/src/styles/tokens.css` | append-only 新增 `--fs-input-mobile: 16px`（不改任何既有 token） |
| `frontend/src/styles/base.css` | ① `.sc-topbar` 高度/上内边距让出 `env(safe-area-inset-top)`；② `.sc-shell` 追加 `100dvh` 回退；③ `.sc-iq-composer` 底部内边距让出 `env(safe-area-inset-bottom)`；④ r21 的 `<1024` 段内 `.sc-topstepper` 改 `position: sticky`、输入控件字号抬到 `--fs-input-mobile`；⑤ 新增 `@media (max-width: 640px)` 时间线堆叠段 |

## 2. 推导

- **顶栏与导航**：顶栏高 `56 + inset-top`，导航 `top = 56 + inset-top`，两处同一表达式；`env=0` 时高度仍为 56、导航仍在 53 高（44 项 + 4×2 + 分割线 1），与 r21 实测完全一致。导航 `z-index:9` 低于顶栏 `10`，不遮挡。
- **时间线**：`--tl-time-w:120` + 内容 `1fr` + 按钮 `auto` 同排时，390 下正文列仅约 150px；≤640 改为两行网格 `'time toggle' / 'main main'`，正文独占整行。同时取消内层 `max-height: var(--tl-scroll-h=528)` 与 `overflow-y:auto`——`overscroll-behavior: contain` 会让手指落在时间线里时整页滚不动。
- **16px**：iOS Safari 对 `<16px` 输入控件聚焦自动放大整页；行高仍取 `--lh-body`，故 `--iq-composer-h(156)` 与 `--textarea-min-h(128)` 的固定高推导不变。
- **dvh**：`100vh` 取「地址栏收起后的最大视口」，短页面会多出一截滚动；第二行 `100dvh` 跟随当前可视高度，不支持的浏览器落回首行（与 r21 行为相同）。

## 3. 刻意不做

- `--btn-h(40)` / `--chip-h(24)` 触控尺寸不动（牵动 composer 156 链条与筛选区密度，须独立需求）。
- 两个 `@media (max-width:1023px)` 段不合并（历史段被大量页面依赖，合并属重构，风险大于收益）。
- 顶部栏「本地存储」长文案不加快略：320 宽才可能触发，当前目标机型 390。

## 4. 验证

前端四门禁见 `ACCEPTANCE.md` §3；本次未做 390px 浏览器复测（Docker 实例挂在 r21 Basic Auth 后，需用户凭据），移动端视觉结论以静态推导为准并列入 P3。

## 5. 风险与回滚

- 风险：`viewport-fit=cover` 在带刘海/iOS 设备上会让页面延伸到安全区——顶栏与 composer 已让位，页面主体底部由浏览器自身处理；无刘海设备无变化。
- 回滚：删掉 base.css 的 5 处 r22 注释块 + tokens.css 的 `--fs-input-mobile` 块 + index.html 的 `viewport-fit=cover`，即回到 r21 基线。

## 6. 文档指针

- 移动端尺寸与真机待确认项：[r21 DESIGN-MOBILE](../20261102-r21-public-tunnel-auth/DESIGN-MOBILE.md)
- 移动端遗留清单来源：[r21 ACCEPTANCE §4 P3-b](../20261102-r21-public-tunnel-auth/ACCEPTANCE.md)
