# r40 · 移动端可用性收口（360–430 断点）

- 需求：把已上线的 Web 端做成**手机上真正能用**的形态，只做自适应/兼容，不做小程序、不做鸿蒙、不做原生。
- 范围：`frontend/` 5 个文件；后端、HTTP 契约、业务逻辑零改动。
- 日期：2026-11-08

## 1. 结论

前几轮的移动改造集中在导航（r21）与表单字号/时间线（r22），面试与报告局部在 ≤640 有补丁；
其余页面在 390 宽下仍有三类硬伤：**页面级横向溢出没有兜底**、**标签字号低于可读下限**、
**触控目标 24–40px 点不准**。本轮把这些收口，并补上「软键盘收缩视口」「页内锚点被吸顶栏盖住」
「上传页文案说拖拽」三个具体缺口。桌面规则（≥1024）一条未动。

## 2. 逐项改动

| # | 缺口（改前事实） | 改法 | 落点 |
|---|---|---|---|
| 1 | 无页面级横向溢出兜底：卡片里一个长 URL / 长标识符就能把整页拉宽，手机上左右晃 | `html, body { overflow-x: clip }`（≤1023）。用 `clip` 不用 `hidden`：前者不建立新的滚动容器，顶栏/吸顶导航/面试吸底输入区的 `sticky` 不受影响 | base.css r40 §1 |
| 2 | 英文技能名、URL、文件路径在窄屏不断行 | `.sc-page { overflow-wrap: anywhere }`（≤1023） | base.css r40 §2 |
| 3 | 教程小节锚点 `#tutorial-<id>` 跳转后标题被「顶栏 56 + 吸顶导航 53」压住 | `html { scroll-padding-top: 顶栏 + 44 + 12 + safe-area-top }`（≤1023） | base.css r40 §3 |
| 4 | 主按钮 40、chip 24、技能标签 28，拇指点不准 | ≤1023 抬到 `--touch-min`（44）：`.sc-btn:not(.is-sm)`、`.sc-chip.is-clickable`、`.sc-lab-skill`。**`--btn-h` 本身不改**——它被 `--iq-composer-h`(156) 等固定高推导引用 | base.css r40 §4 |
| 5 | 软键盘弹出时吸底输入区可能被压在键盘后（viewport 未声明键盘行为） | `viewport` 增 `interactive-widget=resizes-content`（Chromium/ArkWeb 收缩布局视口）；iOS 不认该值，`Composer` 聚焦后按 `visualViewport` 判断作答框是否被遮挡，**只在遮挡时**补一次滚动 | index.html、Composer.tsx、base.css §5 |
| 6 | 触屏上仍显示「Ctrl/Cmd + Enter 提交」提示（手机没有该键，是噪音） | 提示拆成 `.sc-iq-meta-key` 节点，≤1023 隐藏；字数/计时保留 | Composer.tsx、base.css §5 |
| 7 | 上传页文案写死「拖入或点击选择文件」，手机上拖拽不存在 | 拆成 `.is-drag` / `.is-tap` 两个节点，按断点切换；`accept=".pdf,.docx,.txt"` 与单文件本来就正确，未改 | UploadPage.tsx、base.css §11 |
| 8 | ≤640 单列后 CTA 仍只是左对齐的一小段文字，和上方主文案贴在一起，不像「下一个动作」 | ≤430：CTA `grid-column: 1 / -1` 独占一行 + 顶部发丝线 + 铺满（覆盖 ≤640 的 `justify-self: start`） | base.css r40 §9 |
| 9 | 仪器标签 9.5/10px 在 360–430 低于可读下限 | ≤640 抬到 `--fs-nano`/`--fs-kicker` = 11，行高 14 → 16 | tokens.css r40 |
| 10 | 字号抬高后「PRIMARY」撑破 `.sc-lab-tok` 的 54px 首列 | ≤1023 `.sc-lab-tok-k` 字距 0.12em → 0.04em（55.4 → 49.3，≤ 54） | base.css r40 §12 |
| 11 | 五段流程条在 ≤430 两列每格仅约 150，标题断成三行 | ≤430 单列 | base.css r40 §8 |
| 12 | 弹窗确认/取消两枚按钮挤在右下角 | ≤430 `.sc-modal-actions .sc-btn { flex: 1 1 auto }` 铺满一行 | base.css r40 §10 |
| 13 | 零散 `<pre>` 块会撑宽页面 | ≤1023 `.sc-page pre { max-width: 100%; overflow-x: auto }` | base.css r40 §6 |
| 14 | 深色单主题下 `html` 没有底色：系统是浅色时过滚回弹区/首帧会闪白 | `:root { color-scheme: dark }` + `html { background: var(--bg-canvas) }`；**不做浅色皮肤**（产品是单主题深色） | base.css r40 §0 |
| 15 | 移动浏览器标题栏配色为默认白/灰 | `<meta name="theme-color" content="#070809">`（与 `--bg-canvas` 同值，改色需两处同步） | index.html |

## 3. 八页覆盖矩阵

「既有」= 前几轮已完成并在本轮复核未回归；「本轮」= 本次新增。

| 页面 | 手机端既有保障 | 本轮补的 |
|---|---|---|
| 上传 `/` | r21 横向导航、r22 表单防缩放字号、r35 进度卡左右布局 | 文案拖拽/点击切换、CTA 独占行、留白 16、按钮 44、长文件名断行 |
| 画像 `/profile` | 维度卡 ≤640 单列、长 `sourceQuote` 可换行、编辑行换行 | 技能标签 44 触控、全局断行兜底、留白 16 |
| 面试 `/interview` | r21/r22 吸底输入区（`--iq-scroll-pad` 172 让最后一条气泡完整滚出）、16px 输入防缩放 | `interactive-widget` + 聚焦兜底、隐藏快捷键提示、按钮 44（输入区 160 仍 < 172） |
| 笔试 `/exam` | 筛选 chip `flex-wrap`、题卡与选项单列、结果块换行 | chip 44、留白 16、断行兜底 |
| 报告 `/report` | ≤1023 `--lab-report-cols` 单列、弱项表 ≤640 重排、课程卡单列 | 复制/导出按钮 44、长文本断行、`<pre>` 横滑 |
| 历史 `/history` | r22 时间线 ≤640 卡片化、趋势表 ≤640 卡片化 | 留白 16、断行、按钮 44 |
| 练习 `/practice` | r11/r22 筛选与选项单列、错题行展开 | chip 44、代码块横滑、留白 16 |
| 润色 `/polish` | ≤1319 单栏、成稿区 Tab 可点 | 按钮 44、留白 16、断行 |

## 4. 明确没做

- 不做小程序 / 鸿蒙 / 原生壳；不引入 UI 框架或 CSS 库。
- 不做浅色主题（产品是单主题深色，`prefers-color-scheme: light` 下仍按深色渲染，见 §2-14）。
- 不改后端、不改接口、不动任何请求链路与超时。
- 不改 `--btn-h` / `--iq-composer-h` / `--iq-scroll-pad` 等被推导引用的组件尺寸（原因见 §2-4）。

## 5. 回滚

单点回滚：删除 `index.html` 的 `interactive-widget`、`theme-color` 两个 meta + base.css 文件末尾 r40 段 + tokens.css 末尾 r40 段，
再把 `Composer.tsx` 与 `UploadPage.tsx` 的两处 JSX 还原即可。r40 段全部是 append-only，不与既有规则交叉。
