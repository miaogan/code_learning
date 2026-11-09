# r40 · 移动端尺寸推导（DESIGN 增补）

> 本产品为单主题深色视觉系统，几何推导以 `tokens.css` 为唯一来源。
> r38 视觉改版的设计文档不在当前仓库任务夹内（已随轮次归档），本轮改动按 AGENTS §4
> 「改尺寸必须重算推导并回写设计文档」的要求，全部推导记录于此。

## 0. 约束

- 视口目标：**360 / 390 / 430** 三档；断点沿用既有 1024 / 640，新增 430 作为「超窄」档。
- 桌面（≥1024）**零变化**：r40 全部规则包在 `max-width: 1023px` 或 `max-width: 430px` 里。
- 只允许引用 token；本轮新增规则中没有裸色值、没有裸尺寸。

## 1. 页面留白

```
改前 ≤1023：padding = --lab-page-pad-y-sm(36) · --lab-page-pad-x-sm(24) · --sp-9(56)
360 视口 → 内容宽 = 360 − 24×2 = 312
改后 ≤430：左右 = --sp-4(16)
360 视口 → 内容宽 = 360 − 16×2 = 328（+16，有效宽度 +5.1%）
390 视口 → 358；430 视口 → 398
```

上下留白不变（36 / 56），因为吸顶两条栏已占 109，再压缩会让首屏太挤。

## 2. 触控目标

```
--touch-min = 44（既有 token，r21 导航已用）
主按钮：--btn-h 40 → 实际渲染 44（min-height 覆盖 height）
```

为什么**不改** `--btn-h`：它参与固定高推导

```
--iq-composer-h 156 = padding 12×2 + --iq-input-h 84 + gap 8 + 按钮行 40
--iq-scroll-pad 172 = --iq-composer-h 156 + 16
```

若把 `--btn-h` 改成 44，`--iq-composer-h` 需同步重算为 160、`--iq-scroll-pad` 为 176，
而这两个值还被 `.sc-iq-col` 底部留白与滚动定位引用，连锁面过大。因此只在断点内抬高**渲染高**：

```
实际输入区 = 12 + 84 + 8 + 44 + 12 = 160 < --iq-scroll-pad 172  （余量 12，最后一条气泡仍可完整滚出）
```

`.sc-btn.is-sm`（32）不参与，保持顶栏/密集行的密度。

chip / 技能标签：

```
--lab-chip-h 28、--chip-h 24 → height: auto + min-height: 44
文本行高 --lh-meta 16，垂直方向由 flex 居中分配 (44 − 16)/2 = 14 上下，
不引入新的 padding token。
```

## 3. 字体档位（≤640）

```
--fs-nano:   9.5 → 11   （仪器标签，等宽）
--lh-nano:   14  → 16   （与 --lh-meta 同档）
--fs-kicker: 10  → 11
--lh-kicker: 14  → 16
```

首列容差核算（`.sc-lab-tok` 首列 54px，等宽 ≈ 0.6em/字符）：

```
"PRIMARY" = 7 字符 × 11px × 0.6 = 46.2
原字距 0.12em：46.2 + 7 × 11 × 0.12 = 46.2 + 9.24 = 55.4 > 54   ← 顶破
改 0.04em：   46.2 + 7 × 11 × 0.04 = 46.2 + 3.08 = 49.3 ≤ 54   ← 通过
```

其余列（`58px` / `34px` / `1fr`）内容为「62%」"3/5" 与进度条，11px 下均有余量。

正文不动：`--fs-body` 14、`--fs-meta` 12 在 360–430 属于正常阅读尺寸；
输入框在 r22 已锁定 16px（低于 16 时 iOS 聚焦会自动放大页面）。

## 4. 视口与安全区

```
viewport = width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content
```

- `viewport-fit=cover`（r21 已加）：让 `env(safe-area-inset-*)` 生效。
- `interactive-widget=resizes-content`：软键盘弹出时**收缩布局视口**，吸底输入区随之上移，
  而不是被盖住。Chromium / ArkWeb 支持；iOS Safari 忽略，由 `Composer` 聚焦兜底。
- 锚点滚动补偿：

```
吸顶总高 = --topbar-h(56) + [--touch-min(44) + --sp-1×2(8) + 1px 发丝线] = 109
scroll-padding-top = 56 + 44 + --sp-3(12) + safe-area-top = 112 + inset  （比 109 多 3px 呼吸）
```

## 5. 深色

- 单主题深色，不做浅色皮肤。
- `:root { color-scheme: dark }` 保证原生滚动条/输入控件在系统浅色下仍按深色渲染；
  `html { background: var(--bg-canvas) }` 消除过滚回弹区与首帧白底。
- `theme-color = #070809` 与 `--bg-canvas` 同值，用于移动浏览器地址栏；该值无法读 CSS 变量，
  改色时 HTML 与 token 两处同步（已在 index.html 注释注明）。

## 6. r41 增补（图片简历入口 / 学习计划任务行）

r41 只**新增两个 token**，`--btn-h / --iq-composer-h / --iq-scroll-pad / --touch-min`
等既有推导链一律不动（因此 r40 §2 的连锁核算仍然成立）。

```
--thumb-size = 56 = 7×8（落在 4px 网格）
  360 视口内容宽 328（沿用 r40 §1：360 − --sp-4 16×2）
  3 张缩略图 + 2 个 --sp-2(8) 间隙 = 3×56 + 2×8 = 184 ≤ 328
  余量 144 足够容纳右上删除命中区（透明外扩 44）与「+ 添加」位
  56 同时 ≥ --touch-min 44：缩略图本体也可直接点开替换

--plan-task-min-h = 56
  构成：padding --sp-2(8)×2 + 标题行 --lh-small(20) + gap --sp-1(4) + meta --lh-meta(16)
        16 + 20 + 4 + 16 = 56
  这是**最低行高**：任务行内还有一层 44 高的触控头（勾选 + 标题），
  实际渲染 ≥ 8×2 + 44 + 4 + 16 = 80，远高于 44 触控下限，故 56 只作为兜底下限存在。

时长选择三档按钮复用 --lab-chip-h 28（桌面）/ 移动断点内抬到 --touch-min 44，
不新增第三档高度；计划进度轨复用 --qa-track-h 6。

（勘误：TECH-PLAN §2.5 曾把标题行写成 24，实际标题用 --lh-small 20，已在原表同步修正。）
