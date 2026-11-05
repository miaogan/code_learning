# PRD · 文章页章内目录 + 报告页进度联动（r26）

## 1. 背景

r25 给学习模块接上了阅读进度，但文章页仍是「一条道读到黑」：

- `TutorialArticle` 早就生成了 `id="tutorial-<sectionId>"` 与 `aria-labelledby`，**锚点建好了却没有任何入口**——4 节长文（含代码块）只能靠滚轮找位置；
- 章节固定 4 节且结构相同（概念 → 规则 → 示例 → 常见坑与自测），目录完全可枚举，做导航的成本极低；
- 进度只活在 `/learn` 两页里，报告页推荐了方向却看不出「这个方向读到哪」，用户得自己回学习页才知道。

## 2. 目标

1. **章内可跳转**：正文旁给 4 个小节的锚点目录，宽屏常驻、窄屏折叠。
2. **跳到哪看得见**：当前正在读的小节高亮，目录里同时标出已读小节（✓）与「N/M 节已读」。
3. **不新增状态源**：高亮由滚动位置推导，已读与进度条同源（`sc.learn` 记录），不新增存储键。
4. **报告页可见进度**：方向卡的「站内教程」入口显示该方向已读完章数。

## 3. 方案

### 3.1 高亮：两条观察带，各管一件事

`TutorialArticle` 里同时挂两个 `IntersectionObserver`（都不改 DOM 结构，仍用 `data-section-id` 定位）：

| 观察器 | rootMargin | 用途 |
|---|---|---|
| 已读 | `0 0 -25% 0`（视口上部 75%） | r25 已有：小节进来即记 `seen` |
| 高亮 | `0 0 -60% 0`（视口上部 40%） | 只做触发时机，回调里按各节顶边重算（见 §3.5） |

- 当前小节 = **最后一个顶边越过 40% 线的小节**（`activeSectionIndex`）——按「谁在带里」判定会滞后一节（§3.5）；
- 一节都没越线（页首）时回落第 0 节，目录不会全灰。

### 3.2 目录形态

- **≥1280px**：正文右栏 220px 常驻，`position: sticky` 顶到 `topbar + sp-4`；`<details>` 的 summary 退化成标题行（去掉三角与 pointer）；
- **<1280px**：`<details>` 默认收起，只占一行「本章目录 · 2/4 节已读」，点开才展开；
- 展开态由 `matchMedia('(min-width: 1280px)')` 决定初值，跨断点时自动切换，用户手动展开/收起不会被后续渲染覆盖；
- 链接用 `<a href="#tutorial-<sectionId>">`（不用 `RouterLink`）：只改 hash、浏览器原生滚动、可直接分享；`aria-current="location"` 标出当前项，已读用 ✓ plus `aria-label` 文案，颜色不是唯一信息。

### 3.3 报告页

`LearningDirectionCard` 的「站内教程」入口：该方向有读完章节时显示 `3 章 · 已读完 2`，否则维持 `3 章 · 概念到自测`。进度来自 `useLearnProgress()`，不引入后端字段。

### 3.4 不做

章内滚动进度百分比、H2/H3 多级目录（章节固定 4 节，没有层级）、目录折叠态记忆、全文搜索。

### 3.5 截图实测后修正（2026-11-05 下午）

r26 上线后用 Playwright（mock `/api/me` + 本地 dev server）截图实测，发现并修掉两处：

1. **高亮滞后一节**：原实现「谁在视口上部 40% 的带里谁高亮」，滚到第 3 节时第 2 节的尾巴还在带里，目录亮的是第 2 节。改为：观察器只做触发时机，回调里按各节**顶边相对视口**重算，取最后一个顶边越过 40% 线的小节（`activeSectionIndex`，纯函数有测试）。页首一节都没越线时回落第 0 节。
2. **进度条横贯整卡**：继续学习卡与章节卡的进度条 `flex: 1` 拉满整卡宽，视觉上像分隔线而不是进度。继续学习卡限宽 240px，章节卡限宽 180px 并与状态文字成组；继续学习卡的 CTA 移到右上角（kicker 同行 space-between），卡片从五段压到四段。

章内滚动进度百分比、H2/H3 多级目录（章节固定 4 节，没有层级）、目录折叠态记忆、全文搜索。

## 4. 验收标准

- AC-1 宽屏（≥1280px）目录常驻右栏并随滚动吸附；窄屏默认收起为一行，可展开。
- AC-2 目录项点击后页面落到对应小节（锚点带 `scroll-margin-top`，不被顶栏遮住）。
- AC-3 当前小节随滚动高亮，且同一时刻只有一个高亮项；`aria-current="location"` 同步。
- AC-4 已读小节显示 ✓，与进度条「读到 N/M 节」计数一致（同源 `seen`）。
- AC-5 换章时高亮清空，不会先亮旧章序号。
- AC-6 报告页方向卡的站内教程入口能显示已读完章数，未读时文案不变。
- AC-7 类型检查、lint、单测、构建全绿；r24 筛选与 r25 进度零回归。

## 5. 验证

```bash
cd frontend
npm run typecheck && npm run lint && npm test -- --run && npm run build
```

结果：typecheck 通过；lint 0 warning；17 个测试文件 / **196 条用例**通过（教程 20 条含新增 3 条高亮相关）；`dist/` 构建正常。

## 6. 改动清单

| 文件 | 变化 |
|---|---|
| `components/learn/TutorialToc.tsx` | 新增：`<details>` 目录，宽屏常驻 / 窄屏折叠，含已读标记与 `aria-current` |
| `components/learn/TutorialArticle.tsx` | 观察器拆成「已读」「高亮」两条带，新增 `onActiveSectionChange` |
| `lib/tutorials.ts` | 新增 `activeSectionIndex(tops, line)`：最后一个顶边越过判定线的小节下标（§3.5 修订） |
| `pages/TutorialPage.tsx` | 包一层 `.sc-learn-layout`，维护 `activeSectionId`，换章清空 |
| `components/report/LearningDirectionCard.tsx` | 站内教程入口显示已读完章数 |
| `styles/base.css` | `.sc-learn-layout`、`.sc-learn-toc*`（1280px 断点常驻 / 折叠态） |
| `test/tutorials.test.ts` | 新增 3 条：高亮取值、空集合、锚点 id 形状 |
