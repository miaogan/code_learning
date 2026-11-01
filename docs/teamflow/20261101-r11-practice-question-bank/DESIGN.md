<!-- meta: summary="r11 练习页 /practice 的视觉与交互规格：第一屏是「观感意图」（表面/状态/动效/字体/反模式/5 个新 token 与几何核算），其后是筛选设置态、逐题作答态、解析折叠、完成态、错题本与五空态文案、390 堆叠顺序、无障碍焦点态；全部复用 .sc-card/.sc-qcard/.sc-opt/.sc-iq-chip 词汇，判断题零新控件（走既有单选分支），题型标签只加一个 judge→「判断」的中文映射。" -->
基线依赖：`docs/teamflow/20261031-r1-dev-skill-coach`（`.sc-card` / `.sc-btn` / `.sc-chip` / `.sc-empty` / `.sc-inline-error` / `.sc-opt` / 栅格与 token 体系、侧栏工具组）、`docs/teamflow/20261101-r6-exam-proficiency-filter`（笔试题卡 `.sc-qcard`、判分口径、熟练过滤）、`docs/teamflow/20261101-r5-interview-chat-config`（`.sc-iq-chip` 单选 chip 组与 32 高 chip 口径）、`docs/teamflow/20261101-r7-diagnosis-coach-blocks`（表面/状态/反模式的书写口径）。

**本需求不取代任何既有 AC**：全部为增补（新路由 + 新页面 + 题卡所在组件的两处「只加映射/插槽」小改）。

# r11 · 在线练习题库 · 设计说明

**定位一句话**：`/practice` 是「补短板」的练习场，不是新的展示层——它复用笔试题卡的**同一套作答控件**（`.sc-qcard` + `.sc-opt`），把「筛选 → 逐题作答 → 即时对错与解析 → 错题重练」串成一条安静的、可反复走的工作流。

---

## 0. 观感意图（先读这一节，实现时不需要猜）

### 0.1 基调（一句可执行）

**深色、低对比、密度优先、零装饰**：练习页要**比报告页更安静**——它是用户每天来刷 10 道题的操作台，不是战报。整页只允许三种强调色出现：`--accent`（当前选中/主按钮）、`--success`（答对）、`--danger`（答错）。**没有渐变、没有发光、没有入场动画**；一切可信度来自等宽数字 + 紧凑对齐 + 稳定不跳动。

### 0.2 表面处理（Surface treatment · 逐组件，数值写死）

| 元素 | 规格 |
|---|---|
| 页面容器【沿用】 | `.sc-page`（max `--content-max` 1080、padding `--sp-6` 24）；页内内容列宽 `--qa-col-w` 880，**左对齐**（右侧留 152 呼吸，同 r5 `--iq-col-w` 口径），不居中、不撑满 1032 |
| 页头【沿用】 | `.sc-page-header` + `.sc-page-title` 24/32 600 + `.sc-page-sub` 14/22 `--text-secondary` |
| 顶部「练习 / 错题本」分段切换【沿用】 | `SegTabs`（`.sc-seg-tabs` 高 40、底 `--bg-inset` inset、选中项抬到 `--bg-raised`）；**需给 `SegTabs` 增加可选 `ariaLabel` prop**（默认文案保持「原版与润色版切换」不变，既有 vitest 断言不受影响），练习页传「练习与错题本切换」 |
| 卡片【沿用】 | 一律 `.sc-card`：底 `--bg-surface`、1px `--border-subtle`、`--radius-12`、`--elev-1`、padding `--sp-5`(20)。**不新建卡面、不用 `--elev-2`（只属于 Modal）** |
| 筛选 chip【沿用】 | `.sc-chip .sc-iq-chip`：高 32(`--btn-h-sm`)、`--radius-pill`、padding 0 12、13/20；未选：底 `--overlay-06`、边 `--border-subtle`、字 `--text-secondary`；已选：底 `--accent-tint`、边 `--accent`、字 `--text-primary`，**文案前加「✓ 」双通道标记**（颜色不是唯一信息） |
| 「范围 / 题量」二组【沿用同一套】 | 同样是单选 chip 组（**不要用 `<select>`**：深色下无 token 可用的原生下拉会白底）；题量 chip 文案「10 题 / 20 题 / 全部」 |
| 题卡【沿用】 | `.sc-qcard`（`Card` 内 flex column、gap 12）：头行 `.sc-qcard-head` = `Q3`（mono 12/16）+ 题型 chip + 方向 chip（`.sc-chip--direction`）+ 语言 chip（中性 `.sc-chip`）；题面 `.sc-qcard-prompt` 16/24 500 `--text-primary` |
| 选项【沿用】 | `.sc-opt`：整行 40 高、`--radius-8`、1px `--border-subtle`、底 `--overlay-02`、原生 radio/checkbox 14px（`accent-color: --accent`）、左侧 mono `A/B/C` 键 12/16 `--text-tertiary`；选中 = 边 `--accent` + 底 `--accent-tint` + inset 2px 左竖条（既有效果，不改） |
| 代码块【新增类】 | `.sc-qa-code`：`pre`，底 `--bg-inset`、1px `--border-hair`、`--radius-8`、padding 12、`--font-mono` 13/20 `--text-primary`；`overflow: auto`，`max-height: --qa-code-max-h`(320)；**页面与卡片本身永不横向滚动**（横向只在 `pre` 内）。行内 `code` 用 `.sc-qa-code-inline`：mono 12/16、底 `--overlay-06`、`--radius-4`、padding 0 4 |
| 判分反馈块【新增类】 | `.sc-qa-feedback`：`--bg-inset` 内嵌面、1px `--border-hair`、`--radius-8`、padding 12，**不用 success/danger 整块底色**（底色只给「正确答案」那一个 chip）；行一 = 结果徽标 + `正确答案：B`（mono）+ 右侧折叠按钮；行二 = 解析正文 13/20 `--text-secondary`，左侧 2px `--accent` 竖线（沿用 `.sc-source-quote` 口径） |
| 结果徽标【新增类】 | `.sc-qa-mark`：13/20 600，`✓ 正确` = `--success`，`✗ 错误` = `--danger`；**不带底色块、不带图标库**（纯文字双通道，读屏可读） |
| 进度轨【新增类】 | `.sc-qa-track`：高 `--qa-track-h`(6)、`--radius-pill`、底 `--overlay-06`；`.sc-qa-track-fill` 底 `--accent`、同高、宽度按 `(已答/总题数)`；**轨内不承载任何文字** |
| 完成态数字【新增类】 | `.sc-qa-rate`：`--fs-value-md` 32/40 600 mono + 后缀 `%` 20/28 `--text-secondary`；下方一行 13/20 `--text-secondary` |
| 错题行【新增类】 | `.sc-qa-wrong-row`：1px `--border-subtle`、`--radius-8`、padding 12、**min-height `--qa-row-min-h`(78)**、底 `--bg-surface`；行内无右对齐按钮列（重练是列表级动作）；题面单行截断 + 「展开」文字按钮；meta 行用 `.sc-chip` + mono 时间 |
| 提示/说明文字【沿用】 | `.sc-meta-line` 12/16 `--text-tertiary`；**但「正确答案：X」与「解析」标题不得用 `--text-tertiary`**（关键信息取 `--text-secondary` 以上，见 §5 对比度） |
| 难度/语言等标签色 | 一律中性 chip；**不给难度上色**（避免与对错色抢注意力），挑战题也不加警告色 |

### 0.3 状态反馈（每个状态都要能看见；时长/曲线写死）

| 元素 | hover | active/pressed | focus-visible | disabled / 静态 |
|---|---|---|---|---|
| 筛选 chip（未选） | 边 `--border-strong`、底 `--overlay-06`，`--fast`(120ms) `--ease` | 底 `--overlay-10` | 全局 2px `--accent` + offset 2 | 统计请求中：仍可点（**不禁用**，避免连点被吞），仅命中行显示「统计中…」 |
| 筛选 chip（已选） | 不变化（保持选中态，防止误以为会取消） | 底 `--accent-tint` 加深为 `--accent-line-30` | 同上 | 带「✓」前缀常驻 |
| 开始练习按钮 | `.sc-btn--primary` 既有 hover | 既有 | 既有 | 0 命中 / 题单加载中 = `disabled`（`.sc-btn:disabled` 既有样式），且按钮下方常驻一行 12/16 `--text-tertiary` 说明「当前筛选没有题目」 |
| 选项 `.sc-opt` | 边 `--border-strong`、底 `--overlay-06`（既有） | 无 | 原生 radio/checkbox 焦点环（全局） | 提交后 `aria-disabled` + 只读，保留选中色；判分后正确项 `is-correct`、错选项 `is-wrong`（既有三态，**顺序即优先级**） |
| 提交答案按钮 | 既有 | 既有 | 既有 | 未选任何选项**不禁用**（避免死按钮）：点击后选项组下方出现 `.sc-qa-need` 13/20 `--danger` 文案「先选一个答案，再提交」，焦点移到该文案（`tabindex="-1"`） |
| 判分中 | — | — | — | 按钮文案变「判分中…」+ `.sc-btn.is-loading` 的 `.sc-spinner`；选项组保持可读但 `aria-disabled` |
| 折叠按钮（解析/题面） | 字 `--text-secondary`→`--text-primary`，120ms | 底 `--overlay-04` | 全局焦点环 | `aria-expanded` 驱动箭头 180° 翻转 120ms；**内容直接挂载/卸载，不做高度动画** |
| 错题行「展开」 | 同上文字 hover | 同上 | 全局 | 展开后按钮变「收起」，行高转 auto |
| 错题重练按钮 | `.sc-btn--primary` 既有 | 既有 | 既有 | 错题本 0 条时不渲染该按钮（空态承接） |

### 0.4 动效 · 加载 / 空 / 错误

- **入场：零动画。** 页面、卡片、反馈块一律条件挂载，不加 opacity/位移/stagger（与 r6/r7 一致：练习结果是事实，不是「刚发生的一件事」）。
- **允许的两处运动**（仅此两处）：
  1. 进度轨填充宽度 `--base`(180ms) `--ease`（答完一题后的推进感）；
  2. 折叠箭头 120ms 旋转。
- `prefers-reduced-motion: reduce` 下两者均取消过渡（沿用 `base.css` 既有 reduce 块口径）。
- **加载**：题单统计/题单请求走既有 `PhaseLoader`——统计「正在读取题库统计」phases `['读取题库统计','统计已练与错题']`；开始练习 phases `['按筛选挑题','准备题单']`（≤2 句，不新增第三句）。判分是同步本地计算（≤50ms），**只显示按钮 loading，不出加载页**（否则像在等 AI）。
- **空/错误**：五态文案见 §2.5，一律「原因 + 可操作出口」，**禁止只写「暂无数据」**；加载失败一律 `InlineError`（页内，按 r2 约定不用 Toast）。

### 0.5 字体角色与数字对齐

| 角色 | 规格 |
|---|---|
| 页面标题 | 24/32 600 `--text-primary`（`.sc-page-title`） |
| 区块标题（「筛选」「错题本」） | 16/24 600 `--text-primary` |
| 题面 | 16/24 500 `--text-primary`（`.sc-qcard-prompt`） |
| 选项正文 | 14/22 `--text-primary`；键 `A/B` mono 12/16 `--text-tertiary` |
| 解析正文 | 13/20 `--text-secondary` |
| 徽标/反馈 | 13/20 600（`✓ 正确` / `✗ 错误`） |
| 进度与计数 | 全部 `--font-mono` + `tabular-nums`：`第 3 / 10 题` 16/19；`正确 2 · 正确率 67%` 13/20；`已练 37 / 260` 13/20 |
| 完成率大数 | 32/40 600 mono + `%` 20/28（**等宽，换轮次不跳动**） |
| 时间/次数 | `最近答错 11-01 20:12`、`答错 3 次` mono 12/16 `--text-tertiary`（`MM-dd HH:mm`，定宽 11 字符） |

数字统一 `font-variant-numeric: tabular-nums`；**禁止比例字体数字**（轮次切换会跳列）。

### 0.6 本产品反模式（明确禁止，逐条可观察）

1. **提交前任何地方出现答案痕迹**：选项不加「高频考点/常考」徽标、不把正确项排第一、DOM 与接口都不带 `answer/explanation/correct`（AC 与 anti-goal 3）。
2. **给练习页加战争片视觉**：渐变背景、发光边、粒子/彩带、答对弹窗庆祝——练习是日常动作，庆功一次就会腻。
3. **解析默认折叠**：提交后必须直接看到解析正文（PRD 默认展开）；折叠是可选动作，不是默认。
4. **失败用 Toast**：判分失败必须页内 `InlineError` 且**保留已选答案**；用 Toast 会丢上下文。
5. **空态只说「暂无数据」**：必须有原因句 + 出口（放宽筛选 / 重试 / 去练习）。
6. **筛选器用原生 `<select>`**：深色主题下会出现白底下拉；一律 chip 组。
7. **判断题新控件**：不做「✓/✗ 大按钮」、不做 switch、不做滑块——判断题就是 `A 正确 / B 错误` 的两选项单选（AC-6 零新分支）。
8. **裸色值/裸尺寸**：只用 `tokens.css`；本文件 §0.7 之外不新增任何尺寸（AC-7 断言 0 裸色值）。
9. **进度条内塞文字**（如「6/10」压在 6px 轨上）——几何上必然溢出，见 §0.7 第 2 条。
10. **一次会话内重复出同一题**：题卡去重是硬口径（AC-8），前端若做重试也不得把已答题目重新塞回题单。

### 0.7 新增 token 与几何核算（`tokens.css` 末尾追加 r11 块；既有值一个不改）

```css
/* ---------- r11 · 练习页（append-only；改值必须重算本节推导） ---------- */
:root {
  /* 内容列 880：内容区 1032（1080 − 24×2）− 880 = 152 右侧留白，左对齐，同 r5 --iq-col-w 口径 */
  --qa-col-w: 880px;
  /* 进度轨 6 = 2×3：pill 圆角下等效全圆；6 高在 880 宽下 1% 填充仍可见（≥4px 最小可见）；轨内不放文字 */
  --qa-track-h: 6px;
  /* 代码块最大可视高 320 = 14 行(14×20=280) + padding-y 12×2(24) + 边框 1×2(2) + 14 余量（容纳横向滚动条 8–12，不遮末行） */
  --qa-code-max-h: 320px;
  /* 错题行最小高 78 = padding-y 12×2(24) + 题面单行 22 + gap 8 + meta 行 24；展开态转 auto */
  --qa-row-min-h: 78px;
  /* 筛选标签列 96：最长「必备度」3 汉字 3×14=42 + 右侧呼吸 54，保证 4 行标签左缘对齐 */
  --qa-label-w: 96px;
}
```

**几何自洽核算（逐条，写死结论）**

1. **筛选行**：卡片内宽 = 880 − 2×20 = 840；`label 96 + gap 16` 后 chips 区 **728**。语言 11 个 chip 中最长 `TypeScript` 13px 正文 10 字符 ≈ 73 + padding 24 = 97 ≤ 728 → 每行容 6 个（6×97 + 5×8 = 622），11 个 chip 恒 **2 行**，不出现单个 chip 被压窄换行（`white-space: nowrap`）。
2. **进度轨**：6px 形体内**不含文字**；`第 i / N 题`（16/19，最长「第 10 / 10 题」≈ 105px）与右侧统计（13/20，最长「正确 10 · 正确率 100%」≈ 145px）在 390 视口的内容宽 358 内：105 + 16 + 145 = 266 ≤ 358 → **390 下仍单行**，无需换行降级。
3. **错题行**：题面单行 22 + meta 行固定 24 + gap 8 + padding 24 = 78，作为 `min-height`——**内容永不撑破固定行高**；展开态改 `height: auto`，长题面/代码块在行内向下生长，不覆盖相邻行（无 absolute 定位）。
4. **代码块**：`max-height: 320` 时可视 14 行折叠；横向滚动条落在余量 14 内 → 末行不被遮。`overflow-x: auto` 只在 `pre` 内部，**页面 `scrollWidth == clientWidth`**（AC-17 断言）。
5. **判分反馈块**：无固定高度（解析长度不定），常驻可见 = 行一 32（折叠按钮 `--btn-h-sm`）+ gap 8 + 解析至少 2 行 40 + padding 24 = **104**，此为最小观感高度，不设 token（高度随内容）。
6. **完成态大数**：`100%` = 32 号 mono 4 字符 4×19.2=76.8 + `%` 20 号 1 字符 12 ≈ 89 ≤ 880，390 下 ≈ 89 ≤ 358 → 不换行、不缩字号。
7. **封闭形状**：本页**不新增任何「文字被包在固定尺寸形状里」的构件**（进度轨 6px 内无文字、徽标为无底色的纯文字、chip 由内容自撑宽高），故不涉及「半径 − 描边 ≥ 文字半对角」约束；判分徽标刻意不用环（避免把正确率塞进 64 环）。

### 0.8 390px 断点（沿用 `@media (max-width: 640px)`，不新增断点）

- 筛选行：`flex-direction: column`，标签在上、chips 在下（`--qa-label-w` 失效）；
- 页内两列/横排一律转纵向：进度行（`第 i / N 题` 与统计各占一行）、完成态按钮全宽 40 高、错题行 meta 行换行；
- 所有 chip 允许换行（`flex-wrap: wrap`，行间距 `--sp-2`）；
- 代码块保持横向滚动、页面无横向滚动；
- 页头 `.sc-page-sub` 满宽 2 行内；页面 padding 沿用 `.sc-page` 的 24（既有 390 口径）。

---

## 1. 页面清单与信息架构

### 1.1 路由与导航【新增】

- 新路由 `/practice`，挂在既有壳内（`.sc-main > .sc-page`）；**不进 5 步主线 stepper**（主线是「画像→面试→笔试→报告」，练习是旁挂能力，与 `/history`、`/polish` 同级）。
- 侧栏「工具」组 `TOOL_ITEMS` 增一项并**排在首位**：`{ key: 'practice', label: '练习', to: '/practice' }` → 工具组顺序变为 **练习 / 成绩趋势 / 简历润色**（练习是当前主动作，放最上）。`ToolNav` 组件不改。
- 页内二级导航不新增：用 `SegTabs` 两个 tab —— **练习 / 错题本（带条数，如「错题本 3」）**。

### 1.2 文件落点【新增 / 修订】

| 文件 | 动作 | 说明 |
|---|---|---|
| `frontend/src/pages/PracticePage.tsx` | 新增 | 页面壳 + `view` 状态机（`setup / running / done` + `gate / error`）+ 错题本 tab 切换；只经 `api` 出网 |
| `frontend/src/components/practice/PracticeFilters.tsx` | 新增 | 5 组 chip 筛选 + 命中行 + 开始按钮（纯展示 + 回调，不发请求） |
| `frontend/src/components/practice/Explanation.tsx` | 新增 | 解析折叠块（默认展开，`aria-expanded` + `aria-controls`） |
| `frontend/src/components/practice/PracticeProgress.tsx` | 新增 | 进度行 + `.sc-qa-track`（`role="progressbar"`） |
| `frontend/src/components/practice/PracticeSummary.tsx` | 新增 | 完成态（正确率大数 + 三出口） |
| `frontend/src/components/practice/WrongBookList.tsx` | 新增 | 错题行 + 展开 + 列表级「错题重练」 |
| `frontend/src/components/exam/ExamQuestionCard.tsx` | **修订（两处，零分支）** | ① `KIND_LABEL` 增 `judge: '判断'`（纯文案映射；渲染仍走 `kind !== 'multiple'` 的单选分支）；② 新增可选 `footer?: ReactNode`（渲染在选项组之后、`Card` 之内），练习页把解析块作为 footer 传入，**共享同一套选项染色/锁定逻辑**，不复制第二份选项渲染 |
| `frontend/src/components/polish/SegTabs.tsx` | **修订（一处）** | 新增可选 `ariaLabel?: string`（默认值保持原文案「原版与润色版切换」），供练习页传「练习与错题本切换」；其余行为不变 |
| `frontend/src/pages/ExamPage.tsx` | **零改动**（预期） | 判断题进笔试的降级闸门：若实测必须改 kind 分支才可渲染，则本版 `judge` 不进笔试卷（PRD §11 第 1 条），练习页不受影响 |
| `frontend/src/App.tsx` | 修订 | 增 `<Route path="/practice" element={<PracticePage />} />` + `TOOL_ITEMS` 首项 |
| `frontend/src/styles/base.css` | 追加 | 仅追加 r11 段（`.sc-qa-*`），不改既有块 |
| `frontend/src/styles/tokens.css` | 追加 | 仅追加 §0.7 的 5 个 token |
| `frontend/src/api/types.ts` / `client.ts` | 修订 | 契约镜像（tech 阶段定稿），设计侧只要求：题单响应**不含** `answer/explanation/correct` |

### 1.3 信息架构（数据 → 视觉）

```
GET 题库统计（总题数 M / 已练 m / 错题数 n / 当前筛选命中 N）
  └→ 设置态：命中行「当前组合命中 N 题」+ 底行「全库已练 m / M」+ 错题本 tab 角标 n

POST 题单（筛选 + scope + limit）→ 题目数组（id / prompt / kind / options / language / direction / difficulty / essentiality）
  └→ 作答态：进度行（第 i/N、正确数、正确率）+ 题卡（语言/方向/题型 chip + 题面 + 选项）

POST 判分（题 id + 选择）→ { correct, correct_answer, explanation }
  └→ 反馈块（徽标 + 正确答案 + 解析）+ 卡片选项三态染色 + 进度推进

GET 错题本（按语言筛选）→ 行（题面摘要 / 语言·方向·难度 / 最近答错时间 / 答错次数）
  └→ 错题本 tab：列表 + 列表级「错题重练」→ 复用作答态
```

**中文展示映射（前端唯一新增的业务文案表，集中一处）**

| 字段值 | 展示 |
|---|---|
| `language` | `""`→通用；`html`→HTML；`css`→CSS；`js`→JavaScript；`ts`→TypeScript；`vue3`→Vue 3；`react`→React；`python`→Python；`java`→Java；`go`→Go |
| `kind` | `single`→单选；`multiple`→多选；`judge`→判断（`text` 不进练习池） |
| `difficulty` | `basic`→基础；`intermediate`→进阶；`challenge`→挑战 |
| `essentiality` | `must_know`→必须掌握；`advanced`→进阶；`nice_to_know`→加分项 |
| `scope` | `all`→全部；`unseen`→只看未做过；`wrong`→只看错题 |
| `limit` | `10`/`20`→10 题 / 20 题；`0`→全部 |

---

## 2. 关键页线框（布局 / 组件 / 状态）

### 2.1 设置态（`/practice` · tab=练习 · `setup`）

```
┌ .sc-page (padding 24) ──────────────────────────────────────────────┐
│ 在线练习                                          ← .sc-page-title  │
│ 按语言挑题，提交即出对错与解析；判分与笔试同源，答对会累计进熟练度     │
│ ┌SegTabs 练习 | 错题本 3 ────────────────────────────────────────┐ │
│ ┌ Card 筛选 (880) ────────────────────────────────────────────────┐ │
│ │ 语言   [✓ 全部][通用][Python][Java][Go]                          │ │
│ │        [HTML][CSS][JavaScript][TypeScript][Vue 3][React]         │ │
│ │        通用 = 算法与数据结构 / 计算机基础（language 为空）  ← 12/16│ │
│ │ 方向   [✓ 全部][前端][后端][算法与数据结构][计算机基础]            │ │
│ │ 难度   [✓ 全部][基础][进阶][挑战]                                 │ │
│ │ 必备度 [✓ 全部][必须掌握][进阶][加分项]                            │ │
│ │ 范围   [✓ 全部][只看未做过][只看错题]                              │ │
│ │ 题量   [✓ 10 题][20 题][全部]                                     │ │
│ │ ── 1px --border-hair ─────────────────────────────────────────── │ │
│ │ 当前组合命中 142 题        ← 13/20；0 命中时整行换为原因 + 建议按钮  │ │
│ │ 全库已练 37 / 260          ← mono 13/20 --text-secondary           │ │
│ │                     [开始练习 · 10 题]  ← primary 40，右对齐        │ │
│ └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

要点：
- 6 行筛选 = **同一套 chip 组**（单选，点击即生效，不设「应用」按钮）；行间 `--sp-3`，chips 间 `--sp-2`，`flex-wrap: wrap`。
- 「全部」恒为首个 chip，且**每组恰有一个选中**（无「清空」态，消除不确定）。
- 命中行常驻（不因 200ms 请求闪烁消失）：请求中显示「统计中…」占位，宽度用 `min-height` 固定 20 行高防跳动。
- 0 命中：命中行换成 `--danger`? **不用 danger**（不是错误）→ 13/20 `--text-secondary` 文案「该组合下没有题目，试试放宽难度或必备度」+ 三个建议 chip「难度=全部」「必备度=全部」「方向=全部」（点击直接改筛选并重算）；开始按钮 `disabled`。
- `开始练习 · {10 题|20 题|全部 N 题}`：`limit=0` 时若命中 M 与全部同，写「全部 N 题」；N>50 时仍照实写（不做二次确认，避免多一步）。

### 2.2 作答态（`running`）

```
┌ 进度行 (880) ───────────────────────────────────────────────────────┐
│ 第 3 / 10 题        [Python][后端][进阶][判断]      正确 2 · 正确率 67%│
│ ▓▓▓▓▓▓▓▓░░░░░░░░░░░░  ← .sc-qa-track 6px 满列宽                      │
│ ┌ Card 题卡 ──────────────────────────────────────────────────────┐ │
│ │ Q3  [判断] [后端] [Python]                          ← 头行 mono+chip│ │
│ │ 在 CPython 中，`list.append()` 在多数情况下是 O(1) 摊还复杂度。      │ │
│ │  ┌ 代码块（可选，max-h 320，内部可滚动） ┐                         │ │
│ │  │ x = []; x.append(1)                  │                         │ │
│ │  └──────────────────────────────────────┘                         │ │
│ │ (A) 正确     ← .sc-opt radio 40 高整行可点                         │ │
│ │ (B) 错误                                                          │ │
│ │ ── 提交后在此处出现 footer 反馈块（§2.3）──                         │ │
│ │ [提交答案]  ← 未选时点击 → 选项组下方红字「先选一个答案，再提交」     │ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

- 单选/多选/判断**同一张卡**：`multiple`→checkbox 多选；`single` 与 `judge`→radio 单选（**判断题零新控件**，AC-6）。
- 判断题选项文案固定 `A 正确` / `B 错误`，顺序不随机、不打乱（读屏与肌肉记忆稳定）。
- 进度行右端统计：`正确 n · 正确率 p%`，p 由前端 `n/已答数` 取整；**已答数为 0 时不显示正确率**（只显示「正确 0」）。
- 按钮区：未判分 = 单个「提交答案」（primary，右对齐）；判分后 = 「下一题」（primary，末题文案「查看本轮结果」）。**不做「跳过」**（跳过后该题无作答事件，会破坏 unseen 口径）。
- 退出：进度行右侧 `.sc-btn--ghost.is-sm`「退出本轮」→ 复用既有 `ConfirmModal`（「退出后本轮进度不保留，已提交的对错仍会计入熟练度」/ 取消 / 退出）；退出后回 `setup` 并重新取统计。

### 2.3 反馈块（题卡内 `footer`，判分后立即出现）

```
┌ .sc-qa-feedback（bg-inset，radius 8，padding 12） ───────────────────┐
│ ✓ 正确       正确答案：A                       [收起解析 ⌄]  ← 32 高  │
│ │ O(1) 摊还：CPython 的 list 预留了容量，扩容时才整体复制…            │
│ │ 错误项「错误」之所以不对：…                                        │
└──────────────────────────────────────────────────────────────────────┘
```

- 行一：`.sc-qa-mark`（`✓ 正确` 绿 / `✗ 错误` 红，13/20 600）+ `正确答案：` 12/16 `--text-secondary` + 键位 mono 13/20 `--text-primary`（多选写 `A、C`，两个以上用「、」分隔，不缩写）。
- 行一右端折叠按钮 `.sc-btn--ghost.is-sm`：文案「收起解析 / 展开解析」，`aria-expanded` + `aria-controls` 指向正文 `id`。
- 行二：`border-left: 2px solid var(--accent)` + padding-left 12 的解析正文（沿用 `.sc-source-quote` 口径），13/20 `--text-secondary`；解析中允许代码块（`.sc-qa-code`，同样 max-h）。
- **默认展开**（PRD 决策）；收起后行一只留徽标 + 正确答案 + 展开按钮，块高 ≈ 56（32 + 24 padding）。
- 判断题解析必须解释该陈述为何为真/假（内容口径在 TECHNICAL；设计侧只要求**同块同位置呈现，不新增题型专属 UI**）。
- 无障碍：反馈块 `role="status"` + `aria-live="polite"`，提交成功后把焦点移到块首（`tabindex="-1"`），读屏先读「✓ 正确，正确答案 A」，再读解析。

### 2.4 完成态（`done`）

```
┌ Card (880) ─────────────────────────────────────────────────────────┐
│ 本轮完成                                                            │
│ 67%            ← .sc-qa-rate 32/40 600 mono + % 20/28               │
│ 本轮 10 题，答对 7 道 · 本次筛选：Python / 后端 / 全部难度            │
│ ── 1px --border-hair ────────────────────────────────────────────── │
│ [去错题本 3]  [再来一轮]  [回到筛选]      ← 40 高，左对齐，gap 12     │
└─────────────────────────────────────────────────────────────────────┘
```

- 「去错题本」= `secondary`，切到错题本 tab 并刷新；「再来一轮」= `primary`，**沿用当前筛选**重新取题单（新 session，计数归零）；「回到筛选」= `ghost`，回 `setup`。
- 正确率 0 题时（理论上不出现，仍兜底）：显示 `—` 与「本轮没有作答记录」。

### 2.5 错题本态（tab=错题本）

```
┌ 错题本 ─────────────────────────────────────────────────────────────┐
│ 语言 [✓ 全部][Python][Java][Go][JavaScript]…           共 7 道        │
│ 答错一次就会进来，答对一次即移出（最近一次作答口径）      ← 12/16     │
│ ┌ .sc-qa-wrong-row ──────────────────────────────────────────────┐  │
│ │ 下列关于 Vue 3 响应式系统的说法，正确的是…            [展开]     │  │
│ │ [Vue 3][前端][进阶]   最近答错 11-01 20:12   答错 3 次           │  │
│ └────────────────────────────────────────────────────────────────┘  │
│ … 行间 gap 8 …                                                      │
│                                            [错题重练 · 7 题]  ← primary│
└─────────────────────────────────────────────────────────────────────┘
```

- 排序：最近答错时间倒序（服务端定序，前端不二次排序）；语言筛选为单选 chip 组（「全部」+9 语言，**不列空串「通用」以外的额外项**：错题本按语言过滤，通用题只在「全部」下出现，避免两个 chip 语义重叠——文案注明「通用题在「全部」中」作为 12/16 提示）。
- 行内容：题面单行截断（`text-overflow: ellipsis`，≥60 字符截断后加「…」）+ 右侧「展开 / 收起」文字按钮（展开显示完整题面与代码块，行高 auto）；meta 行 = 3 个 chip + mono 时间 + mono 次数。
- 空：`EmptyState` reason「练习里答错的题会自动进来，答对一次就移出」，action「开始练习」（切回练习 tab）。
- 「错题重练 · N 题」：以当前筛选下的错题为题单开新一轮 → 切到练习 tab 进入 `running`（进度行标题区显示「错题重练」小 chip，避免用户误以为是普通一轮）。

### 2.6 五态与文案（AC-13，逐字）

| 状态 | 触发 | 渲染 |
|---|---|---|
| 题库未就绪 | 统计/题单返回空且总题数 = 0 | `EmptyState` reason「题库未就绪，暂时没有可练习的题目」 action「重试」 |
| 筛选无结果 | 命中 0（非错误，200 + 空列表） | 命中行换文案「该组合下没有题目，试试放宽难度或必备度」+ 3 个建议 chip；开始按钮 disabled |
| 题单加载失败 | 请求异常 | `InlineError`（沿用组件）+ 「重试」；筛选保持原选择 |
| 判分失败 | 判分请求异常 | 题卡内 `InlineError`「判分失败，你的选择已保留，可直接重试」+ 重试；**选项与已选不变** |
| 错题本为空 / 判分前 | `n=0` | 见 §2.5 空态 |
| 会话完成 | 末题后 | 见 §2.4 |
| 统计加载中（`gate`） | 首屏 | `PhaseLoader`「正在读取题库统计」phases 2 句 |

### 2.7 390px 堆叠顺序（AC-17）

1. 页头（标题 → 副标题 2 行）
2. SegTabs（练习 / 错题本）—— 满宽，两 tab 各 50%
3. 筛选 Card：每组「标签行 → chips 行（换行）」纵向堆叠；语言 11 chip 约 3–4 行
4. 命中行 → 全库进度 → 开始按钮（满宽 40 高）
5. 作答态：进度行（两行）→ 进度轨 → 题卡（题面 → 代码块内部横滚 → 选项 → 反馈块 → 按钮满宽）
6. 完成态：大数 → 说明 → 按钮纵向满宽（去错题本 / 再来一轮 / 回到筛选）
7. 错题本：语言 chips（换行）→ 行（题面 2 行截断 + 展开 + meta 换行）→ 重练按钮满宽
8. 断言：`document.scrollingElement.scrollWidth <= clientWidth`（不出现页面横向滚动）。

---

## 3. 交互与动效细则

1. **筛选即生效**：chip 点击 → 本地状态更新（选中标记立刻变）→ 触发统计/题单重取；不做 300ms 防抖以外的手动确认（连续点击以最后一次为准，用请求序号丢弃过期响应，避免慢响应覆盖新筛选）。
2. **开始练习**：按钮进入 `.is-loading`；成功 → `running`（题单为空则回 `setup` 并展示无结果态）；失败 → `InlineError` 在按钮上方，保留筛选。
3. **作答**：单选点击同一项不取消（radio 语义）；多选可取消；提交前不发任何网络请求（**提交前页面零答案信息**）。
4. **提交**：`提交答案` → 请求期间选项 `aria-disabled`（防改答案导致判分与显示不一致）→ 返回后写入本题结果：选项三态染色（`is-correct` 优先于 `is-wrong` 优先于 `is-selected`）+ 反馈块出现 + 焦点移到反馈块 + 进度推进 180ms。
5. **下一题**：清空本题选择并挂载下一题（同页替换，不路由跳转）；焦点移到题面（`tabindex="-1"`），读屏读「第 4 / 10 题」。末题按钮改「查看本轮结果」→ `done`。
6. **错误重试**：判分失败保留 `answers[qid]`；点击重试复用同一选择，不重开题单。
7. **错题本**：首次切 tab 才请求；切回练习 tab 时若本轮仍在进行则保持不重置；「去错题本」后 tab 角标与列表同步刷新（以服务端返回为准，前端不做本地加减）。
8. **刷新**：本轮进度允许重置（AC-18）；全库「已练 m / M」恒来自服务端。
9. **路由离开**（侧栏点其他页）：直接离开，本轮丢弃（无确认弹窗，避免拦截导航；只有页内「退出本轮」按钮带确认）。

---

## 4. 组件与样式规格（可直接抄）

**新增类（`base.css` 末尾 r11 段，只用 token）**

| 类 | 关键声明 |
|---|---|
| `.sc-qa-col` | `width: 100%; max-width: var(--qa-col-w);`（左对齐，`margin-right: auto`） |
| `.sc-qa-filter-row` | `display:flex; gap: var(--sp-4); align-items:flex-start; padding: var(--sp-3) 0;` 行间 `border-top: 1px solid var(--border-hair)`（首行无） |
| `.sc-qa-filter-label` | `flex: 0 0 var(--qa-label-w); font-size: var(--fs-body); line-height: var(--lh-body); color: var(--text-secondary);` |
| `.sc-qa-chips` | `display:flex; flex-wrap:wrap; gap: var(--sp-2); min-width: 0;` |
| `.sc-qa-hit` | `display:flex; flex-wrap:wrap; align-items:center; gap: var(--sp-2); min-height: var(--lh-small); font-size: var(--fs-small); color: var(--text-secondary);` |
| `.sc-qa-hit-count` | `.sc-mono` + `font-size: var(--fs-value-sm); color: var(--text-primary);`（命中数放大：唯一的「数字强调」） |
| `.sc-qa-footer-row` | `display:flex; justify-content:flex-end; gap: var(--sp-2); padding-top: var(--sp-2);` |
| `.sc-qa-progress` | `display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap: var(--sp-2); font-size: var(--fs-small); color: var(--text-secondary);` |
| `.sc-qa-track` | `height: var(--qa-track-h); border-radius: var(--radius-pill); background: var(--overlay-06); overflow: hidden;` |
| `.sc-qa-track-fill` | `height: 100%; background: var(--accent); border-radius: inherit; transition: width var(--base) var(--ease);` |
| `.sc-qa-code` | `margin: 0; max-height: var(--qa-code-max-h); overflow: auto; padding: var(--sp-3); border: 1px solid var(--border-hair); border-radius: var(--radius-8); background: var(--bg-inset); font-family: var(--font-mono); font-size: var(--fs-small); line-height: var(--lh-small); color: var(--text-primary);` |
| `.sc-qa-code-inline` | `padding: 0 var(--sp-1); border-radius: var(--radius-4); background: var(--overlay-06); font-family: var(--font-mono); font-size: var(--fs-meta);` |
| `.sc-qa-feedback` | `display:flex; flex-direction:column; gap: var(--sp-2); padding: var(--sp-3); border: 1px solid var(--border-hair); border-radius: var(--radius-8); background: var(--bg-inset);` |
| `.sc-qa-feedback-head` | `display:flex; flex-wrap:wrap; align-items:center; gap: var(--sp-2);` |
| `.sc-qa-mark` | `font-size: var(--fs-small); line-height: var(--lh-small); font-weight: 600;` + `.is-correct{color:var(--success)}` `.is-wrong{color:var(--danger)}` |
| `.sc-qa-exp` | `margin:0; padding-left: var(--sp-3); border-left: 2px solid var(--accent); font-size: var(--fs-small); line-height: var(--lh-small); color: var(--text-secondary); white-space: pre-wrap;` |
| `.sc-qa-need` | `font-size: var(--fs-small); line-height: var(--lh-small); color: var(--danger);` |
| `.sc-qa-rate` | `font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: var(--fs-value-md); line-height: var(--lh-value-md); font-weight: 600; color: var(--text-primary);` |
| `.sc-qa-wrong-row` | `display:flex; flex-direction:column; gap: var(--sp-2); min-height: var(--qa-row-min-h); padding: var(--sp-3); border: 1px solid var(--border-subtle); border-radius: var(--radius-8); background: var(--bg-surface);` |
| `.sc-qa-wrong-prompt` | `display:flex; align-items:center; gap: var(--sp-2); min-width: 0; font-size: var(--fs-body); line-height: var(--lh-body); color: var(--text-primary);`（题面 `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`；展开态改 `white-space:normal`） |
| `.sc-qa-split` | `height: 1px; background: var(--border-hair); margin: var(--sp-3) 0;` |

**复用不改的类**：`.sc-card` `.sc-btn(--primary/--secondary/--ghost/is-sm/is-loading)` `.sc-chip(--direction)` `.sc-iq-chip` `.sc-qcard*` `.sc-opt*` `.sc-ring`（本轮不用）`.sc-empty` `.sc-inline-error` `.sc-phase` `.sc-seg-tabs` `.sc-mono` `.sc-meta-line` `.sc-delta-up/down`。

**组件接口（实现切分）**

```
PracticeFilters  props: { filters, onChange(patch), hitCount, hitLoading, globalStats, onStart, startLoading }
Explanation      props: { text, defaultOpen?: boolean }
PracticeProgress props: { index, total, correct, answered }
PracticeSummary  props: { total, correct, wrongCount, filtersLabel, onWrongBook, onAgain, onReset }
WrongBookList    props: { items, expandedId, onToggle, onRetrain, onFilterLanguage }
ExamQuestionCard 新增: { footer?: ReactNode; }  KIND_LABEL 增 judge
```

---

## 5. 可访问性要点

1. **选项语义**：选项组用 `<fieldset>` + `<legend class="sc-sr-only">第 3 题选项</legend>`（视觉上不显示，读屏读全）；radio 用同 `name` 分组；判断题同为 radio 两项。
2. **筛选 chip**：容器 `role="group"` + `aria-label="语言筛选"`（各组不同名）；每 chip 为 `<button type="button" aria-pressed={selected}>`，选中态文案带「✓」。
3. **进度**：`.sc-qa-track` 加 `role="progressbar" aria-valuemin=0 aria-valuemax={N} aria-valuenow={i} aria-label="本轮进度"`；进度行文本本身也完整可读（不依赖图形）。
4. **判分反馈**：反馈块 `role="status" aria-live="polite"`；提交后焦点移至块首；**「正确答案」与「解析」标题用 `--text-secondary`**（不用 tertiary，保证 12–13px 下对比度 ≥4.5:1）。
5. **折叠**：按钮 `aria-expanded` + `aria-controls`；展开/收起不移动焦点；内容 `id` 稳定。
6. **焦点顺序**：页头 → tab → 筛选各组 → 命中/全库 → 开始 → 题卡（题面 → 选项 → 按钮）→ 反馈；换题后焦点落在题面（`tabindex="-1"` + 可编程聚焦）。
7. **颜色非唯一信息**：对错同时有 `✓/✗` 与「正确/错误」文字；选中 chip 有「✓」；难度/语言 chip 有文字。
8. **触摸目标**：所有可点元素 ≥ 32×32（chip 32 高、按钮 40 高、行按钮 32 高，与 r5 口径一致）；390 下按钮满宽 40 高。
9. **键盘**：chip 组 `Tab` 逐个可达（不做 roving tabindex，避免与既有页不一致）；题卡内 radio 原生方向键切换。
10. **不使用仅 hover 的信息**：错题「展开」在触屏也可见可点。

---

## 6. 与 AC 的对照（自检）

| AC | 设计侧落点 |
|---|---|
| AC-6 判断题零新控件 | §2.2（`kind !== 'multiple'` 走单选分支、`A 正确/B 错误`）、§1.2（`KIND_LABEL` 只加映射 + `footer` 插槽，无渲染分支） |
| AC-7 筛选与入口 | §1.1（/practice + 工具组首位）、§2.1（5 组 chip + 范围/题量）、§4（0 裸色值） |
| AC-8 逐题作答与即时反馈 | §2.2 / §2.3（未作答红字提示、徽标 + 正确答案 + 默认展开解析 + 进度 + 末题完成态） |
| AC-9 未做/错题口径 | §2.1（范围组）、§2.5（错题本口径说明行）、§2.6 |
| AC-10 错题本与重练 | §2.5（行内容/排序/展开/语言过滤/列表级重练 + 空态） |
| AC-13 五态 | §2.6 与 §0.4（InlineError 不用 Toast） |
| AC-16 设计交付 | 本文件 §0–§5 |
| AC-17 390 | §0.8 / §2.7（堆叠顺序 + `scrollWidth` 断言 + 代码块内部滚动） |
| AC-18 进度可见 | §2.1（全库已练 m/M）、§2.2（第 i/N、正确 n、正确率） |
| anti-goal 3 提交前零泄露 | §0.1 / §0.6-1 / §1.3（题单响应无答案字段）、§3-3 |
| anti-goal 4 筛选不骗人 | §2.1（0 命中原因 + 建议 chip）、§1.3（返回 100% 命中筛选） |
