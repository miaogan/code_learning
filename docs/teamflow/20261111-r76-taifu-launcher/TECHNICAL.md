# r76 · 技术方案：太傅悬浮壳与位置记忆

> 依据 PRD `docs/teamflow/20261111-r76-taifu-launcher/PRD.md`。纯前端，无后端、无契约、无新依赖；新增 3 个视觉 token。

## 1. 视觉方案对比（用户否决了第一版）

| 方案 | 形态 | 结果 |
| --- | --- | --- |
| A · 青玉方印 | 56×56 圆角方形，青玉底 + 双线内框 + 单字「傅」 | **采纳**：与朝堂隐喻同源，方形比圆形更「印」而不「客服」 |
| B · 圆形蓝底单字 | 56 圆，主色实心，白字「傅」 | 用户直接否决：「图标有点丑」——像客服浮标，与产品气质不符 |
| C · 文字胶囊 | 「问太傅」横条 | 否决：占宽、挡内容，且不像常驻件 |

方案 A 的落地要点：

- 方形 + 4px 内框（`::after` + `inset: var(--sp-1)`）做出「印」的双层结构，避免纯色块的廉价感。
- 字用 `--font-serif`（宋体族），与「诏令 / 卷宗」气质一致；不加阴影堆叠，只留 `--elev-2` 一档。
- 悬停只提亮描边、不放大（避免浮标式跳动）；拖动时 `cursor: grabbing` + `is-dragging` 降透明度。

## 2. 位置与尺寸常量（单一出处）

全部集中在 `frontend/src/lib/taifuPosition.ts`，页面与样式不各自写数字：

| 常量 | 值 | 理由 |
| --- | --- | --- |
| `TAIFU_SIZE` | 56 | 与既有 FAB / 环形进度同级，触屏命中面积够（56 ≥ 44 最小可点） |
| `TAIFU_EDGE` | 8 | 夹紧边距，避免贴边被圆角裁切 |
| `TAIFU_DEFAULT_RIGHT` | 24 | 与 Toast 的右 24 同列 |
| `TAIFU_DEFAULT_BOTTOM` | 88 | **刻意高于 Toast 的 24**：Toast 2s 出现时不能压在印章上，88 = 24 + Toast 高约 48 + 16 间距 |
| `TAIFU_PANEL_WIDTH` | 400 | 桌面浮窗宽，约等于正文栏宽的一半，不压满屏 |
| `TAIFU_PANEL_HEIGHT` | 600 | 上限；实际按上下可用空间缩 |
| `TAIFU_PANEL_GAP` | 12 | 浮窗与印章间距，保证「从印章长出来」的视觉关系 |
| `TAIFU_MOBILE_BREAKPOINT` | 640 | 与全站断点一致，≤640 交给 CSS 底部面板 |
| `TAIFU_STORAGE_VERSION` | 1 | 存储结构版本 |

**为什么用像素而不是百分比**：移动端浏览器地址栏收放会改变 `innerHeight`，百分比会把印章从右下推到页面中部；像素位置 + 每次 `resize` 重新夹紧更可控。代价是换视口后位置不会「按比例」保持，但这正是期望行为（用户记住的是「右下角」这个位置，不是 87.3% 这个比例）。

## 3. 位置算法

### 3.1 夹紧

```ts
maxX = max(TAIFU_EDGE, width - TAIFU_SIZE - TAIFU_EDGE)
maxY = max(TAIFU_EDGE, height - TAIFU_SIZE - TAIFU_EDGE)
```

`Math.max` 兜住「视口比印章还小」的退化情形（此时 maxX < EDGE，不夹紧会得到负数）。非有限数（NaN / Infinity）一律回落 `TAIFU_EDGE`，防止 inline style 输出 `NaNpx` 让元素消失。

### 3.2 浮窗布局（`taifuPanelLayout`)

```ts
spaceAbove = max(0, position.y - GAP - EDGE)
spaceBelow = max(0, height - (position.y + SIZE) - GAP - EDGE)
putAbove   = spaceAbove >= spaceBelow
panelHeight =
  spaceAbove >= maxPanelHeight ? maxPanelHeight
  : spaceBelow >= maxPanelHeight ? maxPanelHeight
  : spaceAbove >= spaceBelow ? spaceAbove : spaceBelow
```

两条不变量：

1. **不压印章**：`top` 只由「印章上方」或「印章下方」两种分支算出，不存在「贴边盖住印章」的第三条路径。
2. **不溢出视口**：`height` 恒 ≤ 该侧可用空间，内部 `overflow-y: auto` 消化超出内容。

返回 `null` 表示窄屏——**这是有意的**：窄屏布局由 CSS media query 决定，若此时仍输出 inline `left/top/width`，inline 优先级会压过 media query，底部面板就做不出来。

## 4. 存储契约

| 键 | 介质 | 版本 | 内容 |
| --- | --- | --- | --- |
| `sc.taifu.pos.<userId>` | localStorage | 1 | `{ version: 1, x: number, y: number }`（整数像素） |

沿用 `lib/uploadSession.ts` 的既有范式：

- **匿名不写**：`userId === null` 时 `read` 返回 `null`、`write` 返回 `false`（不落 `sc.taifu.pos.anonymous` 共享键）。组件只接收必填 `userId: string`，实际由 `App.tsx` 在登录后渲染。
- **纯读写**：`read` 不删除键、不写回默认值；损坏数据只在内存里降级，下次拖拽自然覆盖。
- **降级路径**：`JSON.parse` 抛错 / 非对象 / `version` 不符 / `x` `y` 非有限数 → 返回 `null` → 组件用 `defaultTaifuPosition`。
- **越界自我修复**：读到合法但超界的坐标（例如上次在 4K 屏存的 3000），读取时即夹紧到当前视口。
- **写盘失败不阻断**：`setItem` 抛错（隐私模式、配额满）返回 `false`，位置只在本次会话生效。

## 5. 组件状态机（`components/taifu/TaifuLauncher.tsx`）

```
closed ──click(位移<5px)──▶ open ──Esc / 外部 pointerdown / 路由变化──▶ closed
   │                          │
   └──pointerdown → move(≥5px)──▶ dragging ──pointerup/cancel──▶ closed（保留新位置）
```

关键实现细节：

- **Pointer Events 而非 mouse + touch 双份**：`setPointerCapture` 保证指针移出元素后仍收到 `pointermove`，触屏拖拽不会中断；CSS 用 `touch-action: none` 阻断滚动抢事件。
- **5px 阈值**：小于阈值的移动仍算点击，解决「手抖一下就变成拖拽、点不开」。
- **`suppressClickRef`**：拖拽结束后浏览器仍会派发 `click`，用一次性标记吃掉它，避免「拖完自动展开」。
- **`positionRef` 与 state 双写**：`pointermove` 高频触发，`moveTo` 必须读最新值而不是闭包里的旧 state，否则位移会累加错误。
- **`resize` + `visualViewport.resize` 双监听**：前者管桌面缩放，后者管移动端地址栏收放与软键盘。
- **路由变化即收起**：浮窗里的「当前：科考」是上下文的一部分，换页后它就过期了，留着会误导。
- **Esc 后焦点回印章**，外部点击收起不抢焦点；打开时焦点落到关闭按钮，`role="dialog"` + `aria-labelledby` 提供语义。

## 6. 层级与样式

```
topbar 10  <  太傅 15  <  Toast 20  <  Modal 40  <  Select popup 80
```

- 15 的选择依据：必须高于 `position: sticky` 的 topbar（否则滚到底部时印章被顶栏切一半），必须低于 Toast（`z-index: 20`）——操作反馈永远优先于常驻件。
- 样式追加在 `frontend/src/styles/base.css` 末尾（r76 段，约 323 行），类名 `.sc-taifu-*`，**只引用既有 token**：`--sp-*`、`--fs-*`、`--radius-12`、`--elev-2`、`--accent`、`--font-serif`。
- 新增 3 个 token（`tokens.css` r76 段）：`--taifu-panel-w` / `--taifu-panel-h` / `--font-serif`。方印尺寸不设 token——它由 JS 常量 `TAIFU_SIZE` 驱动 inline 定位，两侧各写一份会漂移，样式里用 `56px` 并在注释里指向常量。
- 两处裸尺寸在验收中修正为 token：`inset: 3px → var(--sp-1)`、contextdot `6px → var(--sp-1)`。

## 7. 移动端（≤640px）

```css
.sc-taifu-panel {
  left: var(--sp-3); right: var(--sp-3); top: auto;
  bottom: calc(var(--sp-3) + env(safe-area-inset-bottom));
  width: auto; height: min(72dvh, var(--taifu-panel-h));
  max-height: calc(100dvh - var(--topbar-h) - var(--sp-6));
}
.sc-taifu-badge { display: none; }        /* 窄屏标题栏放不下三个元素 */
.sc-taifu-fab.is-open { opacity: 0; pointer-events: none; }
```

最后一条是验收中发现的**视觉 bug 修复**：底部面板铺满宽度时，右下角的印章会从面板右侧露出一条残边（截图实测）。收起态保持可见，打开态淡出并让出点击。

`@media (prefers-reduced-motion: reduce)` 下关掉入场动画。

## 8. 与问答接入的衔接（下一需求的前置设计）

本轮只交付壳，但壳已经预留了接入位置：

- `sc-taifu-body` 里现在是静态示例，接入后换成消息列表（`aria-live="polite"`）。
- `sc-taifu-composer` 的 `disabled` 去掉即可用；`pageLabelOf(location.pathname)` 已经把「当前页」作为对话上下文的第一条提示（用户问「这里」有指代可解）。
- 服务端应只提供**只读工具**（画像摘要 / 最近测评 / 错题分布 / 学习进度 / 报告短板），回答必须带站内引用（复用 r65 的引用白名单范式：href 不在材料集合即丢弃并计数），额度走 `user_ai` 的 `light` 档。
- 收起状态不请求、不轮询、不预取——常驻件不能有后台开销。

## 9. 已知限制

- 桌面浮窗高度 600 上限下，长对话需内部滚动，没有「展开成大窗」的中间态。
- 位置记忆只存像素坐标，未处理「同一账号在 27 寸与 13 寸之间来回切」的边界（读取时会夹紧，但不会还原到用户在大屏上的原始位置）。
- 多标签页同时拖动会互相覆盖（先写者被后写者覆盖），单人自用场景接受。
- 触屏长按拖动在 iOS Safari 上未经真机验证（DevTools 触屏模拟通过）。
