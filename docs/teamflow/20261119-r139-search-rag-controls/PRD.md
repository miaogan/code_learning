# r139：检索页 RAG 控件上移与样式统一

- 日期：2026-11-19
- 发起：用户反馈「检索功能的最下方的按钮好丑，而且放在最下边不好用」。
- 经确认：用户指的是 RAG 区（03）的模式/语料切换按钮；诉求是**移到顶部 + 换成统一 Chip 风格**。

## 1. 问题

`SearchPage.tsx` 的 RAG section（03 / 向量混合检索）底部有两排控件：

- 模式：`混合 / 语义`（裸 `<button className="is-active">`）
- 语料：`全部 / 题目 / 教程`（同上的裸按钮）

两个问题：

1. **丑**：它们是裸 `<button>`，仅靠 `is-active` 切换态，而 `base.css` 里没有任何针对它们的规则（也没有全局 `button {}` 样式），实际渲染成浏览器默认的灰色小方块，与全站 `sc-chip` / `sc-qa-chip` 设计系统格格不入。
2. **不好用**：它们埋在页面最后一个 section（教程 8 条 + 题库 10 条 + RAG 5 条之后），用户要一路滚到页面最底才能切换检索模式/语料范围；切完又得滚回顶看结果或改关键词。

## 2. 改动

纯前端、零契约改动——`/api/rag/search` 请求体、模式/语料闭集、后端排序口径全部不变。

### 2.1 控件上移

把模式/语料两组控制从 RAG section 内搬到页面顶部的 `.sc-lab-filters`，排在「方向」行之后，成为两个新筛选行：

- 「模式」行：`混合 / 语义`
- 「语料」行：`全部 / 题目 / 教程`

两行都复用现成的单选 `ChipRow` 组件（`components/ui/ChipRow.tsx`），带 `aria-pressed` 选中态与「✓」前缀——和方向筛选、练习页/学馆筛选完全同一套实现与手感，不再另写一套。

语料行补一条 hint：模式与语料只作用于第 03 组向量检索，教程/题库两组不受影响——避免用户误以为这两项会过滤全部结果。

### 2.2 结果组头保留当前状态

控件上移后，用户滚到 RAG 结果区时看不到自己选了什么。在第 03 组的 grouphead 右侧补一个小字标记（`sc-search-barmeta`），实时显示当前「模式 · 语料」，例如 `混合 · 全部` / `语义 · 题目`。只展示、不可点，真正的操作留在顶部。

## 3. 未改动

- RAG 结果项内的「有用 / 没用」反馈按钮：属于结果项操作，位置随结果走，本次不动。
- 题库分页器、方向筛选：位置与行为不变。
- 任何后端代码、API 契约、出网清单（r115 登记制）。

## 4. 验证

- 前端：typecheck / lint / build 全绿；全量 vitest 48 files / 583 tests passed（本机临时目录 EPERM 噪音，CI 为准）；工程门禁 `test_engineering_gates.py` 41/41。
- Playwright mock（`backend/logs/tmp-r139/verify_search_ui.py`，产物 `frontend/logs/tmp-r139/search-top-controls.png`）：
  - 顶部筛选区文本含「模式 / 混合 / 语义 / 语料 / 全部 / 题目 / 教程」，选中态 class 为 `sc-chip sc-iq-chip sc-qa-chip is-clickable`（统一芯片）；
  - RAG section 内旧筛选按钮数 0；组头标记初始 `混合 · 全部`；
  - 点「语义」+「题目」后，组头标记变 `语义 · 题目`，`/api/rag/search` 请求参数 `mode=semantic`、`kinds=['question']`。
