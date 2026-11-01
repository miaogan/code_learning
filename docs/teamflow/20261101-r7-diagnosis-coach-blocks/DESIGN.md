<!-- meta: summary="r7 诊断报告三块旁挂区块的视觉与交互规格：以「提升路线」分区承接短板主轴，三条可复算区块（薄弱地图表 / 简历要点卡 / 竞争力差距表）沿用 r1–r5 的卡片+表格+chip 词汇，只新增 5 个尺寸 token 与 6 个类；含表面/状态/动效/字体角色/反模式、390 逐条推导、润色页 focus 高亮与降级态。" -->

基线依赖：`docs/teamflow/20261031-r1-dev-skill-coach`（报告页骨架、`.sc-card` / `.sc-trend-table` / `.sc-evidence-chip` / `.sc-source-quote` 词汇）、`docs/teamflow/20261031-r3-memory-resume-polish`（润色页三段式建议卡与 `.sc-sugg-card`）、`docs/teamflow/20261101-r5-interview-chat-config`（面试设定徽标口径）、`docs/teamflow/20261101-r6-exam-proficiency-filter`（`--btn-h-sm` 展开按钮口径）

# r7 · 诊断报告提升路线三区块 · 设计说明

**定位一句话**：本轮**不重画任何页面**，只在报告页短板主轴**之后**加一个「提升路线」分区，用既有卡片 / 表格 / chip / 引文块词汇装三块**可复算**的内容；全部视觉增量是「一张表 + 一叠引文卡 + 一张差距表 + 两个降级提示」，另加润色页一处**定位高亮**。

---

## 0. 观感意图（先读这一节，实现时不需要猜）

### 0.1 基调（一句可执行）

**深色、低对比、信息密度优先**：三块区块是「诊断报告的附件」，不是新的展示层——它们必须看起来**比短板卡更安静**（相同的卡面、更少的色块、全靠排版与等宽数字建立可信度）。任何一处出现"更亮、更大、有渐变、有动效"的视觉，都是越权。

### 0.2 表面处理（Surface treatment · 【沿用，零新造】）

| 元素 | 规格 |
|---|---|
| 三个区块容器【沿用】 | 一律复用 `.sc-card`：底 `--bg-surface`、1px `--border-subtle`、`--radius-12`、`--elev-1`、padding `--sp-5`(20)。**不新建卡面、不用双层卡套卡、不用 `--elev-2`** |
| 「提升路线」分区标题【新增类】 | 汉字 20/28(`--fs-section/--lh-section`) 600 `--text-primary`；分区上沿一条 1px `--border-hair` 分隔线，`padding-top: --sp-6`(24)、`margin-top: --sp-7`(32) |
| 区块小标题【新增类】 | 汉字 16/24(`--fs-card/--lh-card`) 600 `--text-primary`；右侧说明文字 12/16 400 `--text-tertiary` |
| 表格【沿用】 | 复用 `.sc-trend-table`：表头 12/16 500 `--text-tertiary` + 1px `--border-subtle` 下边线；单元格 13–14px `--text-secondary`，行间 1px `--border-hair`；无竖线、无斑马纹 |
| 关键数字【沿用】 | `.sc-mono`（`--font-mono` + `tabular-nums`）右对齐；错误率/差距/得分一律等宽，**禁止比例字体数字**（换行时列会跳） |
| 标记 chip【沿用】 | `.sc-chip`（高 `--chip-h` 24、`--radius-4`、1px `--border-subtle`、`--overlay-06` 底、12/16 500 `--text-secondary`）；证据 chip 用 `.sc-evidence-chip`（等宽 12/16） |
| 原句引文块【沿用】 | 复用 `.sc-source-quote` + `.sc-source-quote-label`：底 `--bg-inset`、左 2px `--accent`、`--radius-4`、13/20 `--text-secondary` |
| 先补序号圆点【新增类】 | 24×24(`--prio-dot`)、`--radius-pill`、底 `--accent-tint`、1px `--accent-line-30`、字 `--accent` 12/16 600 等宽、内容居中 |
| 缺失必备技能 chip【新增类】 | 高 24、1px `--warn-line-35`、底 `--warn-tint-12`、字 `--warn` 12/16 500；**不用 danger**（danger 只属于短板严重度） |
| 来源徽标【沿用】 | 中性 `.sc-chip`，文案「来源：本次面试设定 / 简历画像」，不用强调色 |
| 焦点高亮（润色页）【新增类】 | 卡面 1px `--accent` + 左 2px `--accent` + `--elev-accent` + 底 `--accent-wash-06`；**这是全文档唯一允许用 `--elev-accent` 的新位置** |

### 0.3 状态反馈（每个状态都要能看见）

| 元素 | hover | active/pressed | focus-visible | disabled / 静态 |
|---|---|---|---|---|
| 表格行 | 底 `--overlay-03`（`.sc-trend-table` 既有） | 无（行不可点） | 无（行不可聚焦） | — |
| 折叠按钮【新增类】 | 字 `--text-tertiary`→`--text-secondary`，`--fast`(120ms) `--ease` | 底 `--overlay-04` | 全局 `:focus-visible`（2px `--accent` + offset 2） | `aria-expanded` 决定箭头 180° 翻转，120ms |
| 「去改这一条」跳转【沿用】 | `.sc-btn--secondary` 既有 hover | 既有 | 既有 | 无目标时不渲染（AC-6） |
| 先补 1/2/3 行 | 无（不可点） | 无 | 无 | 序号圆点常驻可见 |
| 润色建议卡定位高亮 | 不叠加（高亮态优先级高于 hover 的边框变化） | 无 | 卡 `tabindex="-1"` 被程序聚焦时全局焦点环 + 高亮态**同时**可见 | 用户点卡片内任一按钮后高亮保留（不闪一下消失） |
| 提示条（降级/占位） | 无 | 无 | 无 | 12/16 `--text-tertiary`，行首不挂图标 |

### 0.4 动效与空态

- **入场：无。** 三块随报告数据一次性渲染（React 条件挂载），不加 opacity/位移/stagger。理由同 r6：它们是**报告事实**，不是"刚刚发生了一件事"；给报告加淡入会让「重新生成」显得缓慢。
- **唯一新增动效**：润色页定位（`scrollIntoView` + 高亮 180ms `--base` `--ease`）；`prefers-reduced-motion: reduce` 时滚动改 `auto`、高亮无过渡（沿用 base.css 既有 reduce 块口径）。
- **折叠展开**：直接条件挂载，**不做 `max-height` 动画**（8 行表格高度不定，动画会抖动）；箭头翻转 120ms 是唯一运动。
- **加载**：报告生成沿用既有 `PhaseLoader` 三句（「汇总作答记录 / 定位短板 / 匹配课程」），**不新增第四句**（新增润色调用 ≤8s 且失败降级，不改既有等待承诺，避免 vitest 既有断言回归）。
- **空/降级形态**（文案逐字，来自 PRD AC-6/10/19 与 AC-13）：

| 区块 | 条件 | 渲染 |
|---|---|---|
| A 薄弱地图 | `weakness_map` 存在但为空 | 单行 `本次测评还没有可统计的计分题`（12/16 `--text-tertiary`，卡内无表格、无表头） |
| A | `weakness_map` 为 `null`/缺字段（旧报告） | 单行 `旧报告不含该区块，重新生成可补全` |
| A | 条数 > 8 | 默认 8 行 + 折叠按钮 `其余 N 条已折叠`，展开后按钮变 `收起` |
| B 简历要点 | `resume_pointers` 为空数组 | `还没有可定位的简历正文，先上传简历再回来看改进要点`，**不渲染任何跳转按钮** |
| B | `null`/缺字段 | `旧报告不含该区块，重新生成可补全` |
| C 竞争力 | `role_fit` 为 `null`/缺字段 | `旧报告不含该区块，重新生成可补全` |
| C | `role_fit` 存在但 `model === null` | `暂无该岗位的能力模型` + 次行 12/16 `--text-tertiary`：`可以先按上面的薄弱地图补，或在简历画像里填写更常见的岗位名` |

### 0.5 字体角色与数字对齐

- 层级只有四档：分区标题 20/28 600 → 区块标题 16/24 600 → 正文 14/22 400（薄弱点名称 500）→ 元信息 12/16 400 `--text-tertiary`。**不新增五档字号。**
- **所有数值走 `.sc-mono` 且右对齐**：错误率（`--fs-value-sm` 16/19）、`错 8 / 共 13 题` 中的数字、能力项 `3 / 5`、差距值、`先补` 序号。数字列宽固定（§0.7），换数字不换布局。
- 中文长名（方向名、能力项名、`anchor_text`）**不省略号截断**，允许换行（`overflow-wrap: anywhere`），因为截断会让「复算」不可核对（反模式 5）。

### 0.6 本产品反模式（明确禁止）

1. **给三块加渐变/发光/彩色大数字**——它们是可复算事实，视觉花哨会让人以为是 AI 生成的营销文案（AC-11 的观感面）。
2. **用环形图/雷达图表达薄弱与差距**——数据点是「方向×难度×必备」的计数，画成图会暗示精度；表格 + 等宽数字才可核对（反面目标 2/4）。
3. **把三块做成 Tab / 折叠面板**——用户拿不到信息，等于没补。
4. **给「提升路线」分区做整块入场动画或 sticky 吸顶**——会把首屏短板挤走（反面目标 1）。
5. **截断方向名/原句用省略号**——点不到、核不上。
6. **错误率写小数（0.62）或分数字符串（62/100）**——统一 `62%`，且必须与 `错 8 / 共 13 题` 同排可见。
7. **新增彩色强调色**（如紫色=竞争力）——本轮颜色语义沿用：`--accent` 结构/动作、`--warn` 缺口、`--danger` 仅短板严重度、`--success` 达标。

### 0.7 新增 token 与逐条推导（`tokens.css` 末尾追加 r7 块，既有值一个不改）

```css
/* ---------- r7 新增组件尺寸（DESIGN r7 §0.7 逐条推导；既有值一个不改） ---------- */
--weak-rank-w: 32px;   /* 序号列：mono 12/16，最大 2 字符 14.4 + 左右 padding 8×2 = 30.4 ≤ 32 */
--weak-rate-w: 64px;   /* 错误率列：mono 16/19 最大 "100%" 4 字符 38.4 + padding 8×2 = 54.4 ≤ 64；
                          表头「错误率」3 汉字 12px = 36 + 16 = 52 ≤ 64（表头与数值同列不溢出） */
--role-level-w: 64px;  /* 「3 / 5」5 字符 mono 13/20 = 39 + padding 8×2 = 55 ≤ 64 */
--role-gap-w: 56px;    /* 「达标」2 汉字 13px = 26 + 16 = 42 ≤ 56；最大差距 "12" mono 15.6 + 16 = 31.6 ≤ 56 */
--prio-dot: 24px;      /* 先补序号圆点 = 字高 16 + 上下各 4 = 24，与 --chip-h 同口径，不新增第三档高度 */
```

**桌面内容宽度推导**：`--content-max` 1080 − 页 padding 24×2 = **1032**；卡内 = 1032 − (20×2) − (1×2) = **990**。

- 薄弱表（3 列）：序号 32 + 错误率 64 = 96，方向列 = 990 − 96 = **894**（6 汉字方向名 84，chip 行 3×40+2×4 = 128，证据 chip 3 条 ≈ 3×82+8 = 254 ≪ 894 → 单行）。
- 差距表（3 列）：`--role-level-w` 64 + `--role-gap-w` 56 = 120，能力项列 = **870**。
- 表内单元格左右 padding 一律 `--sp-2`(8)，与既有 `.sc-trend-table` 的 `td` padding 垂直量（`--sp-3`）一致，**不改既有表格规则，只在新表上用 `:nth-child` 覆盖对齐**。

**390 推导（视口 390 − 页 padding 24×2 = 342）**：卡内 = 342 − 2 − 40 = **300**。

- 薄弱表：序号 32 + 错误率 64 = 96 → 方向列 **204**；方向名 6 汉字 84 ✓；难度/必备 chip 行 3×40+8 = 128 ✓；证据 chip 3 条 254 > 204 → `flex-wrap` 落两行（`.sc-evidence-chip` 在 ≤640 已是「可换行 + 高度自适应」，沿用 390 修复，**无横向滚动**）。
- 差距表：64 + 56 = 120 → 能力项列 **180**；能力项名 ≤8 汉字 112 ✓，必备 chip 40 与其同格换行 ✓。
- 简历要点卡：chip 40 + 位置 ≈96 + 跳转按钮（`-sm` 32 高，5 汉字 13px = 65 + padding 16 = 81）= 217 + gap 16 = 233 ≤ 300 ✓ 单行；若语言变长 `flex-wrap` 落两行。
- 先补 3 行：圆点 24 + gap 8 + 文本 ≤ 268 ✓。
- **禁令**：任何一格若仍超宽，只能换行或加 wrap，**禁止 `overflow-x: auto`**（AC-16 是「无横向滚动」，不是「可横向滚」）。

### 0.8 与 AC-18 改动面白名单的一处冲突（需 tech/QA 明确接受）

AC-18 列出允许改动 `frontend/src/api/types.ts`、`components/report/*`、`pages/ReportPage.tsx`、`pages/PolishPage.tsx`，**未列 `styles/base.css` / `styles/tokens.css`**；但 AC-16 要求新样式只用 token，且本轮必然新增 6 个类（见 §4）与 5 个尺寸 token。设计建议：

- `frontend/src/styles/tokens.css`：**只在末尾追加 §0.7 的 r7 块**（既有声明一行不改）；
- `frontend/src/styles/base.css`：**只在末尾（390 媒体查询之前）追加 r7 一段**，新类全部以 `.sc-coach*` / `.sc-weak*` / `.sc-role*` / `.sc-hint*` / `.sc-prio-*` / `.sc-fold-toggle` 为前缀，不改任何既有选择器；
- 若 QA 坚持白名单逐字：退路是把新增样式写进 `components/report/*.css`（组件局部导入）——**不推荐**（会破「样式单源在 base.css + tokens」的既有团队约定）。此条请技术方案与 QA 在各自阶段显式认领，避免 dev 阶段才发现门禁与白名单互斥。

---

## 1. 页面与信息架构

### 1.1 页面清单【变更标记】

| 路由 | 页面 | 变更 | 说明 |
|---|---|---|---|
| `/report` | 诊断报告 | **修订（本轮主战场）** | 在短板主轴之后新增「提升路线」分区 + 三块（§2.1–2.3） |
| `/polish` | 简历润色 | **修订（仅定位入参 + 高亮）** | 读 `focus/section/anchor`，滚动并高亮对应建议卡；未命中 → section 预筛 + 顶部中文提示（§2.4）。其余布局/成稿区零改动 |
| `/`、`/profile`、`/interview`、`/exam`、`/history` | — | 零改动 | 不改导航顺序、不改任何卡片 |

`ToolNav` 条目与顺序不变。**不新增路由。**

### 1.2 文件落点【新增 / 修订】

| 文件 | 类型 | 内容 |
|---|---|---|
| `frontend/src/components/report/CoachSection.tsx` | **新增** | 「提升路线」分区外壳：分隔线 + h2 + 副说明 + 三个 `<section aria-labelledby>` 容器；负责三块的**顺序与堆叠**（A→B→C） |
| `frontend/src/components/report/WeaknessMap.tsx` | **新增** | 区块 A：表格 + 折叠 + 三种降级态 |
| `frontend/src/components/report/ResumePointers.tsx` | **新增** | 区块 B：3–5 条引文卡 + 跳转链接 + 降级态 |
| `frontend/src/components/report/RoleFit.tsx` | **新增** | 区块 C：目标岗位 + 来源 chip + 差距表 + 先补 3 行 + 缺失必备技能 chip + 降级态 |
| `frontend/src/pages/ReportPage.tsx` | **修订** | 在短板卡 stack 之后挂 `<CoachSection report={report} />`；**不移动、不改动**既有概览卡与短板卡 |
| `frontend/src/pages/PolishPage.tsx` | **修订** | 读 `useSearchParams()`，解析 `focus/section/anchor` → 传给 `SuggestionCard` 的 `isFocused`/`focusSeq`；未命中 → section 预筛 + 顶部提示条 |
| `frontend/src/components/polish/SuggestionCard.tsx` | **修订（最小）** | 新增可选 `focused?: boolean`（追加 `is-focused` 类与 `tabIndex={-1}`）、`onFocused?: () => void`；**既有 props、状态机、文案零改动** |
| `frontend/src/api/types.ts` | **修订** | `weakness_map / resume_pointers / role_fit` 及其内层（snake_case，`Optional`，默认 `null`/`[]`） |
| `styles/tokens.css`、`styles/base.css` | **修订（append-only，见 §0.8）** | §0.7 token 块；§4 新类 |

**不新建页面、不新建卡面组件、不引入图标库**（序号用文字圆点，箭头用 CSS 边框三角或既有字符）。

### 1.3 信息架构（数据 → 视觉）

```
Report { shortfalls(3–5，主轴，不动), weakness_map?, resume_pointers?, role_fit? }
   │
   ├─ 概览卡（面试均分/笔试总分/短板条数/按钮行/润色入口）        ← 既有，零改动
   ├─ 短板卡 stack（3–5 条，按严重度）                          ← 既有，零改动，DOM 位置不变
   └─ 提升路线分区（本轮新增，DOM 在其后，永不前置/吸顶）
        ├─ A 知识薄弱地图：rank | 方向名+摘要+难度/必备 chip+证据 chip | 错误率
        ├─ B 简历改进要点：引文卡（section chip + 位置 + 原句 + 问题 + 去改这一条）
        └─ C 市场竞争力对标：目标岗位名 + 来源 chip | 差距表 | 先补 1/2/3 | 缺失必备技能
```

**层级结论**：三块**同层**、纵向串联，全部比短板卡「更安静」（无主色块）；分区标题是唯一把它们与主轴区分开的元素。**首屏必须仍是概览 + 至少第一条短板卡**（反面目标 1）——因此分区标题只能在短板 stack 之后出现，且不含任何 sticky/absolute 元素。

**字段 → 契约映射（前端只读，不重算）**：

| 视觉元素 | 字段（snake_case） | 约束 |
|---|---|---|
| 薄弱表序号 | 数组下标 +1 | 前端不重排（AC-3 顺序即后端顺序） |
| 方向名 | `weakness_map[].point` | 方向级名称 |
| 摘要 | `.summary` | 后端模板文案，AI 只润色不新增条目 |
| 难度/必备 chip | `.difficulty[]` / `.essentiality[]` → 中文（基础/进阶/挑战；必备/进阶/了解） | 闭集，前端做**展示映射表**，未知值原样显示（不吞） |
| 证据 chip | `.samples[]`（`question_id / score / evidence`） | `evidence` 逐字展示为 `Q3 · 4/10` |
| 错误率 | `.rate`（服务端算好） + `.wrong`/`.total` | 前端**不重算** `wrong/total`；`rate` 直接 `Math.round(rate*100)+'%'`？→ 否：后端给 0–1，前端只做「×100 取整 + %」，**不再做除法** |
| 要点 | `.section / .location / .anchor_text / .issue / .focus_key` | `anchor_text` 逐字渲染，不加引号以外的修饰 |
| 差距 | `role_fit.target_role / role_source / role_source_label / model{level,label} / items[]{name,required,user_level,gap} / missing_must[] / first_fix[] / conclusion / notice` | `first_fix` 若后端不提供则前端取 `items` 前 3，**仅当 `first_fix` 缺省**（AC-20 序号必须与 `items` 顺序一致） |

---

## 2. 关键页线框（布局 / 组件 / 状态）

### 2.1 区块 A · 知识薄弱地图（桌面 1032）

```
┌ Card (.sc-card, radius 12, bg-surface) ────────────────────────────────────┐
│ [h3 16/24 600] 知识薄弱地图         [12/16 tertiary] 必备优先 → 错误率高 → 均分低 │
│ ───────────────────────────────────────────────────────────────────────── ─│
│  #   薄弱方向                                                      错误率    │
│ ──────────────────────────────────────────────────────────────────────────│
│  1   数据库与存储                                        62%   ← mono 16/19  │
│      索引失效导致回表，主要在事务与索引设计上失分        ← 12/16 tertiary 摘要  │
│      [基础][进阶][挑战]  [必备][进阶]                    ← chip 24          │
│      [Q3 · 4/10] [Q7 · 3/10] [Q9 · 5/10]                ← 证据 chip         │
│      错 8 / 共 13 题                                    ← 12/16，数字 mono  │
│ ──────────────────────────────────────────────────────────────────────────│
│  2   …（同构）                                                            │
│ …（最多 8 行）                                                            │
│  [⌄ 其余 5 条已折叠]  ← 展开按钮 32 高（--btn-h-sm），12/16                  │
└───────────────────────────────────────────────────────────────────────────┘
```

- **行内顺序固定**：方向名（14/22 500 `--text-primary`）→ 摘要（12/16 tertiary，最多 2 行后换行不截断）→ chip 行（难度在前、必备级别在后，两个 `gap --sp-1` 的内部组用 `--sp-2` 分隔）→ 证据 chip 行 → `错 x / 共 y 题`。
- **错误率永远与 `错 x / 共 y 题` 同屏出现**（反面目标 2 的唯一防线，缺一即不能验收）。
- 排序说明文案固定为 `必备优先 → 错误率高 → 均分低`（不写算法细节）。
- 表格语义：`<table aria-label="知识薄弱地图">` + `<thead>` + `<tbody>`；**不写 `<caption>`**（标题已由 h3 提供，避免重复播报）。
- 折叠头/尾不加"AI 分析"字样。

**390 线框**：同一表格，方向列 204；chip 行与证据 chip 行按需换行；错误率列右对齐 64；**页面上不出现横向滚动条**。

### 2.2 区块 B · 简历改进要点（3–5 条卡）

```
┌ Card ─────────────────────────────────────────────────────────────────────┐
│ [h3] 简历改进要点   [12/16 tertiary] 只列正文里能逐字定位的条目               │
│                                                                           │
│  ┌ 要点卡（.sc-card 内嵌，padding 16，gap 12）─────────────────────────┐  │
│  │ [chip 项目经历]  项目二 · 第 2 条         [去改这一条 → 32 高 secondary] │  │
│  │ ┌ .sc-source-quote ───────────────────────────────────────────────┐ │  │
│  │ │ 原句                                                             │ │  │
│  │ │ 参与开发了订单系统的后台模块                                      │ │  │
│  │ └─────────────────────────────────────────────────────────────────┘ │  │
│  │ 问题  只写了「参与开发」，没有问题、没有量化结果                      │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│  …（3–5 张，纵向 gap 12，复用 .sc-profile-dim）                            │
└───────────────────────────────────────────────────────────────────────────┘
```

- 跳转是 **`<Link>`**（真实链接，键盘可达、可新标签打开）：`/polish?focus=<focus_key>&section=<section>&anchor=<encodeURIComponent(anchor_text)>`，`anchor` 仅当 `≤120` 字符时携带。
- 文案 `去改这一条` 后缀箭头用文字 `→`（不引图标库）。
- 无简历态：卡内只有一行占位，**不渲染要点卡、不渲染任何跳转**（AC-6）。

### 2.3 区块 C · 市场竞争力对标

```
┌ Card ─────────────────────────────────────────────────────────────────────┐
│ [h3] 市场竞争力对标      [chip] 来源：本次面试设定                          │
│ 目标岗位  后端开发 · 中级（3–5 年）        ← 16/24 600 + 12/16 tertiary 级别 │
│ ──────────────────────────────────────────────────────────────────────── │
│  能力项                                         我的 / 要求        差距     │
│ ──────────────────────────────────────────────────────────────────────── │
│  分布式缓存与一致性                             3 / 5             2        │
│  [必备] 高并发与限流                            2 / 5             3        │
│  服务可观测性                                   5 / 5             达标     │
│ ──────────────────────────────────────────────────────────────────────── │
│  先补什么                                                                 │
│  ❶ 高并发与限流      ❷ 分布式缓存与一致性      ❸ 服务注册与发现            │
│  缺失的必备技能  [Kubernetes][消息队列][单元测试]                          │
│  结论（AI 一句；失败时用模板句）                                            │
└───────────────────────────────────────────────────────────────────────────┘
```

- 差距值：`> 0` 用 `--warn` + 等宽数字；`= 0` 渲染文字 `达标`（`--success`，12/16）——**不用 `0`**（0 与"未统计"歧义）。
- `先补` 的 1/2/3 圆点内容来自 `first_fix` 顺序（缺省取 `items` 前 3），**前端不排序**（AC-20）。
- `缺失的必备技能` 为空时**整行不渲染**（不写「无缺失」占位，避免暗示已达标）。
- `notice`（无模型降级）出现时：不渲染目标岗位行、不渲染差距表/先补/缺失块，只留 `暂无该岗位的能力模型` + 次行引导。

### 2.4 润色页 · 定位高亮（`/polish?focus=…`）

```
顶部（建议列表 head 之上，一条 12/16 提示，仅命中失败时出现）
  未找到对应条目，已按「项目经历」筛选          [显示全部]
逐条建议（6 条）
  ┌ .sc-sugg-card .is-focused  ← 1px accent 边框 + elev-accent + accent-wash-06
  │  [仅措辞建议] 项目经历  目标岗位：后端开发
  │  原句 / 建议句 / 为什么这么改
  │  [采纳][忽略]
  └
```

- 命中：`scrollIntoView({ block: 'center', behavior })`（reduce 时 `auto`）；`scroll-margin-top: calc(var(--topbar-h) + var(--sp-4))` = 72，避免粘性顶栏遮住卡头。
- 高亮**持久**：直到用户点卡内任一按钮、改筛选、或重新进入页面；不自动消退。
- 未命中：按 `section` 预筛（列表只留该 section 的条目，筛选 chip 状态同步，"全部" 仍可点回全量）+ 顶部提示条；`anchor` 不参与模糊匹配（AC-5 只允许逐字相等，否则宁可不定位——反面目标 3）。

---

## 3. 交互与动效细则

| # | 交互 | 规则 |
|---|---|---|
| 1 | 打开报告页 | 三块与数据同帧渲染，无动效；滚动位置不变（不自动滚到新区块） |
| 2 | 展开薄弱地图 | 点击 `其余 N 条已折叠` → 追加剩余行（条件挂载），按钮文案变 `收起`，箭头 180° / 120ms；`aria-expanded` 同步 |
| 3 | 点证据 chip | 复用证据 chip 的「展开复核气泡」既有行为（r1），本轮**不改**；不可跳路由 |
| 4 | 点「去改这一条」 | 路由跳转 `/polish?focus=…`；润色页若尚未生成建议（session 为 null）→ 保留参数，生成完成后再定位一次（只定位一次，用户手动滚动后不再抢焦点） |
| 5 | 定位命中 | 滚动 + `.is-focused` 180ms；卡 `tabindex=-1` 并被程序聚焦（键盘用户焦点环与高亮同时可见，不依赖颜色单一通道） |
| 6 | 定位未命中 | 顶部提示条 + section 预筛；提示条内 `显示全部` 按钮清除 `focus/section/anchor` 三个参数（`history.replace`，不新增历史条目） |
| 7 | 重新生成报告 | 沿用既有：`PhaseLoader` 三句 + 成功后三块整体替换（无局部动画） |
| 8 | 旧报告 | 三块各出一行占位文案，无按钮；`重新生成` 仍由概览卡提供（不在三块里重复 3 个 CTA） |
| 9 | 键盘 Tab 序 | 报告页：概览按钮 → 短板卡内按钮 → 折叠按钮 → 要点卡跳转链接（逐条）。三块**不改变既有 Tab 顺序的前半段** |
| 10 | reduced-motion | 滚动 instant、高亮无过渡、箭头无旋转（沿用 base.css 既有 reduce 块） |

---

## 4. 组件与样式规格（可直接抄）

新增 6 个类（全部 `base.css` append-only），其余全部沿用既有类：

```css
/* ---------- r7 · 报告「提升路线」（DESIGN r7 §2/§4） ---------- */
.sc-coach { display: flex; flex-direction: column; gap: var(--sp-6);
  margin-top: var(--sp-7); padding-top: var(--sp-6); border-top: 1px solid var(--border-hair); }
.sc-coach-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--sp-2); }
.sc-coach-title { margin: 0; font-size: var(--fs-section); line-height: var(--lh-section);
  font-weight: 600; color: var(--text-primary); }
.sc-coach-sub { margin: 0; font-size: var(--fs-meta); line-height: var(--lh-meta); color: var(--text-tertiary); }

/* 区块卡：直接给 .sc-card 追加定位类，只补内部 head/表格对齐，不覆盖卡面 */
.sc-coach-block { display: flex; flex-direction: column; gap: var(--sp-3); }
.sc-coach-blockhead { display: flex; flex-wrap: wrap; align-items: baseline;
  justify-content: space-between; gap: var(--sp-2); }
.sc-coach-blocktitle { margin: 0; font-size: var(--fs-card); line-height: var(--lh-card);
  font-weight: 600; color: var(--text-primary); }
.sc-coach-meta { font-size: var(--fs-meta); line-height: var(--lh-meta); color: var(--text-tertiary); }
.sc-coach-note { margin: 0; font-size: var(--fs-small); line-height: var(--lh-small);
  color: var(--text-tertiary); }

/* 薄弱表：复用 .sc-trend-table，仅重定义三列对齐与宽度 */
.sc-weak-table th:nth-child(n+2), .sc-weak-table td:nth-child(n+2) { text-align: right; }
.sc-weak-table th:nth-child(1), .sc-weak-table td:nth-child(1) { width: var(--weak-rank-w); text-align: right; }
.sc-weak-table th:nth-child(2), .sc-weak-table td:nth-child(2) { text-align: left; }
.sc-weak-table th:last-child, .sc-weak-table td:last-child { width: var(--weak-rate-w); }
.sc-weak-rate { font-size: var(--fs-value-sm); line-height: var(--lh-value-sm); color: var(--text-primary); }
.sc-weak-line { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); }
.sc-weak-name { font-size: var(--fs-body); line-height: var(--lh-body); font-weight: 500; color: var(--text-primary); }
.sc-weak-summary { margin: 0; font-size: var(--fs-meta); line-height: var(--lh-meta);
  color: var(--text-tertiary); overflow-wrap: anywhere; }
.sc-weak-count { font-size: var(--fs-meta); line-height: var(--lh-meta); color: var(--text-tertiary); }

/* 折叠按钮：与 .sc-tl-toggle 同口径（32 高、透明底、0 间距），只是不继承时间线网格 */
.sc-fold-toggle { display: inline-flex; align-items: center; gap: var(--sp-1);
  height: var(--btn-h-sm); padding: 0 var(--sp-2); border: 1px solid transparent;
  border-radius: var(--radius-6); background: transparent; color: var(--text-tertiary);
  font-size: var(--fs-meta); line-height: var(--lh-meta); font-weight: 500; cursor: pointer;
  transition: color var(--fast) var(--ease), background-color var(--fast) var(--ease); }
.sc-fold-toggle:hover { color: var(--text-secondary); background: var(--overlay-04); }
.sc-fold-toggle::before { content: '⌄'; display: inline-block; transition: transform var(--fast) var(--ease); }
.sc-fold-toggle[aria-expanded='true']::before { transform: rotate(180deg); }

/* 简历要点卡：卡面复用 .sc-card，只加 meta 行与问题行 */
.sc-hint { display: flex; flex-direction: column; gap: var(--sp-3); }
.sc-hint-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); }
.sc-hint-loc { font-size: var(--fs-meta); line-height: var(--lh-meta); color: var(--text-tertiary); }
.sc-hint-head .sc-link-btn { margin-left: auto; }   /* 跳转按钮靠右，窄屏换行后自然落到下一行 */
.sc-hint-issue { margin: 0; font-size: var(--fs-body); line-height: var(--lh-body); color: var(--text-primary); }
.sc-hint-label { margin-right: var(--sp-2); font-size: var(--fs-meta); font-weight: 500; color: var(--text-tertiary); }

/* 竞争力：目标岗位行 / 差距表 / 先补 / 缺失 chip */
.sc-role-target { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--sp-2);
  font-size: var(--fs-card); line-height: var(--lh-card); font-weight: 600; color: var(--text-primary); }
.sc-role-target-meta { font-size: var(--fs-meta); line-height: var(--lh-meta); font-weight: 400; color: var(--text-tertiary); }
.sc-role-table { width: 100%; border-collapse: collapse; font-size: var(--fs-body); line-height: var(--lh-body); }
.sc-role-table th { padding: 0 var(--sp-2) var(--sp-2); border-bottom: 1px solid var(--border-subtle);
  font-size: var(--fs-meta); line-height: var(--lh-meta); font-weight: 500; color: var(--text-tertiary); text-align: left; }
.sc-role-table td { padding: var(--sp-3) var(--sp-2); border-bottom: 1px solid var(--border-hair); color: var(--text-secondary); }
.sc-role-table tbody tr:hover td { background: var(--overlay-03); }
.sc-role-table tbody tr:last-child td { border-bottom: 0; }
.sc-role-table th:nth-child(2), .sc-role-table td:nth-child(2) { width: var(--role-level-w); text-align: right; }
.sc-role-table th:nth-child(3), .sc-role-table td:nth-child(3) { width: var(--role-gap-w); text-align: right; }
.sc-role-gap { color: var(--warn); }
.sc-role-met { color: var(--success); font-size: var(--fs-meta); }
.sc-role-prio { display: flex; flex-direction: column; gap: var(--sp-2); margin: 0; padding: 0; list-style: none; }
.sc-role-prio-item { display: flex; align-items: center; gap: var(--sp-2);
  font-size: var(--fs-body); line-height: var(--lh-body); color: var(--text-primary); }
.sc-prio-dot { flex: none; display: inline-flex; align-items: center; justify-content: center;
  width: var(--prio-dot); height: var(--prio-dot); border-radius: var(--radius-pill);
  border: 1px solid var(--accent-line-30); background: var(--accent-tint);
  font-family: var(--font-mono); font-variant-numeric: tabular-nums;
  font-size: var(--fs-meta); line-height: var(--lh-meta); font-weight: 600; color: var(--accent); }
.sc-must-chip { display: inline-flex; align-items: center; height: var(--chip-h); padding: 0 var(--sp-2);
  border: 1px solid var(--warn-line-35); border-radius: var(--radius-4); background: var(--warn-tint-12);
  font-size: var(--fs-meta); line-height: var(--lh-meta); font-weight: 500; color: var(--warn); }

/* 润色页定位高亮（追加在 .sc-sugg-card 既有规则之后，不改既有声明） */
.sc-sugg-card { scroll-margin-top: calc(var(--topbar-h) + var(--sp-4)); }
.sc-sugg-card.is-focused { border-color: var(--accent); border-left-color: var(--accent);
  background: var(--accent-wash-06); box-shadow: var(--elev-accent);
  transition: border-color var(--base) var(--ease), box-shadow var(--base) var(--ease),
    background-color var(--base) var(--ease); }
```

- **焦点环**：不新增，全局 `:focus-visible`（2px `--accent` / offset 2）即可。
- **跳转按钮**：`<Link className="sc-btn sc-btn--secondary is-sm">`（既有），类名 `sc-link-btn` 无需新增（上面的 `margin-left:auto` 用 `.sc-hint-head .sc-btn`）。
- **禁止**：任何组件内写裸色值/裸尺寸（含注释里的色值字面量，`test_engineering_gates.py` 同口径）；不写 `!important`；不改既有 `.sc-card` / `.sc-trend-table` / `.sc-sugg-card` / `.sc-chip` 的任何一行声明。

### 4.1 中文展示映射（前端唯一新增的"业务"逻辑）

```ts
const DIFFICULTY_LABEL = { basic: '基础', intermediate: '进阶', challenge: '挑战' } as const
const ESSENTIALITY_LABEL = { must_know: '必备', advanced: '进阶', nice_to_know: '了解' } as const
// 未知值原样显示（不吞数据、不报错）：label(x) = MAP[x] ?? x
```

顺序即后端数组顺序（**前端不排序、不去重**）。

---

## 5. 可访问性要点

1. **语义**：`提升路线` 是 `<section aria-labelledby>`，三块各为 `<section>` + h3；表格用原生 `<table aria-label>`（薄弱地图 / 能力差距各一）；`先补什么` 用 `<ol>`（序号本身由圆点承载，`ol` 提供读屏顺序）。
2. **颜色不是唯一通道**：`差距>0` 有数字、`达标` 有文字、`缺失必备` 有 chip 文案「必备」；短板严重度语义本轮不动。
3. **键盘**：折叠按钮、跳转链接、提示条内 `显示全部` 全部走原生可聚焦元素；定位命中的建议卡 `tabindex="-1"` 仅用于**程序聚焦**，不进入 Tab 序列（避免插入一个无操作的空焦点站）。
4. **焦点可见**：全局 `:focus-visible` 已覆盖；定位后焦点环与 `.is-focused` 同时可见（不依赖动画）。
5. **读屏**：定位成功时在 `.sc-polish-list` 顶部 `<p role="status" aria-live="polite">已定位到「项目经历」的那一条建议</p>`（**仅键盘/命中时挂载一次**，不随滚动重复播报）；未命中提示条用 `role="status"`。
6. **对比度**：`--text-tertiary`(#7c8da1) 在 `--bg-surface`(#141a23) 上 ≈ 5.1:1（12/16 正文级需求 4.5:1 ✓）；`--warn`/`--success`/`--accent` 均承载图标或文字语义，不单独用色块传达状态。
7. **数字**：`.sc-mono` + `tabular-nums` 保证 8/13、62%、3/5 各列竖直对齐（读屏靠列头语境，不看对齐）。
8. **窄屏**：390 无横向滚动（AC-16）；chip 与证据行 wrap 后高度自适应，不裁切文本。

---

## 6. 与 AC 的对照（自检）

| AC | 设计落实位置 |
|---|---|
| AC-5 跳转定位 | §2.4 命中/未命中两态、§3-#4/#5/#6、`.is-focused` 规格 |
| AC-6 简历缺失 | §0.4 表（B 空数组态）、§2.2 末句 |
| AC-10 无模型降级 | §0.4 表（C 无模型态）、§2.3 末段 |
| AC-12 markdown 单源 | 页面不拼串：三块只渲染字段值；复制/导出仍取 `/markdown` 文本（既有按钮文案与顺序零改动） |
| AC-13 旧报告 | §0.4 表三行「旧报告不含该区块，重新生成可补全」 |
| AC-14 主轴不破 | §1.3「DOM 在短板卡之后，永不前置/吸顶」；既有概览卡与短板卡一字不改 |
| AC-16 样式/390 | §0.7 推导、§4 全部走 token、§6-#8 |
| AC-17 设计交付 | 本文件 |
| AC-19 上限 8 + 折叠 | §2.1 折叠按钮、§0.4 表、§3-#2 |
| AC-20 先补 1/2/3 | §2.3 圆点、§0.2 圆点规格、字段映射（`first_fix` 缺省才取前 3） |
