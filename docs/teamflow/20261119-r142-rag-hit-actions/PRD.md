# r142：RAG 命中项可跳转 + 反馈可见性（检索页第 03 组）

- 日期：2026-11-19
- 发起：用户反馈「向量混合检索是干啥的？有用 / 没用点了只会刷新页面；点击内容也不能跳转到对应问题」。
- 定性：**一个解释缺口 + 两个真缺陷**。反馈链路本身是通的，但界面没有把「已记录」显示出来；
  RAG 命中项只是 `<span>`，根本不是链接。

## 1. 先说清楚「向量混合检索」是什么

第 03 组是站内 RAG 检索组，与 01 教程小节（BM25）、02 题库题面（FTS5）并列：

- 关键词腿与向量腿并行召回，用 RRF(k=60) 融合后取 top-5；
- 可切「混合 / 语义」模式、「全部 / 题目 / 教程」语料范围（r139 已把控件搬到顶部）；
- 「有用 / 没用」写 `rag_feedback`，按**当前用户 + 完全相同的查询词 + 同一 chunk** 计净票，
  融合后加权：up ×1.2、down ×0.6（封顶 3 票，factor 限 [0.2, 2.0]）；
- 配了 rerank 且精排成功时，反馈加权让位给精排序（r119 既有口径）。

所以它不是「另一个题库」：命中仍是教程小节或题目，只是召回与排序方式不同。

## 2. 根因

1. **反馈按钮无状态呈现**：旧代码 `<button className={votes[...] === 'up' ? 'is-active' : ''}>`，
   但 `base.css` 没有任何 `.is-active` 规则，渲染成浏览器默认灰按钮；点击后 `rag.reload()`
   让列表短暂 loading，用户只看到一次刷新。票数变化在第三位小数，确认文案在页脚 notice，
   `votes` 只存在内存里 → 主观上「点了没反应」。
2. **命中项不可点**：教程 / 题库命中是 `<Link className="sc-search-hit">`，只有 RAG 组是
   `<span className="sc-search-hit">`；`.sc-search-hit:hover` 给了箭头变色，看起来像能点，
   实际没有 `href`。
3. **题目没有详情页**：`/practice` 只接受方向 / 二级方向筛选参数，没有按 question_id 深链；
   教程则有现成的 `#tutorial-<sectionId>` 锚点。

## 3. 改动（纯前端，后端契约与检索口径零改动）

### 3.1 跳转映射（`lib/search.ts`）

新增纯函数 `ragHref(item: RagChunkItem)`：

- 教程命中：`/learn/${ref_id}#tutorial-${section_id.split('#')[0]}`。
  `ref_id` 为空时降级到 `/learn`，不生成 `/learn/#tutorial-x` 坏链；
  `#n` 分片后缀只用于 chunk 唯一性，锚点必须取 `#` 前半段（与 `tutorialSearch.ts` 同源）。
- 题目命中：后端把 title 固定写成 `方向 · 二级方向`，拆开后交给既有 `questionHref()`
  落到 `/practice?direction=...&sub=...`，与 02 组题库命中口径完全一致。

### 3.2 命中项结构（`SearchPage.tsx`）

外层由 `<span>` 改 `<div className="sc-search-hit sc-search-hit-rag">`：

- 标题 / 摘要 / 箭头包进 `<Link className="sc-search-hit-main">`，可点击、有 `aria-label`；
- 「有用 / 没用」按钮作为 Link 的**兄弟节点**，避免 `<button>` 嵌进 `<a>` 的点击冲突；
- 不再把整行当链接，避免用户想投票却触发跳转。

### 3.3 反馈可见性

- `votes`（只存 verdict）改为 `voteState`（verdict + 接口返回的 up/down 票数），
  另加 `voteError` 记录提交失败；按钮改用全站统一的
  `sc-chip sc-iq-chip sc-qa-chip is-clickable`，带 `aria-pressed` 与 `✓` 前缀，
  选中态由 `.sc-qa-chip[aria-pressed='true']` 提供（与 r139 顶部控件同一视觉语言）。
- 每条命中下方新增一行 `role="status"`：成功时
  `已记下你的「有用」反馈 · 该项累计 N 赞 / M 踩，会影响你后续同词检索的排序`；
  失败时明确提示「反馈没提交成功，请再点一次」，不再静默吞错。
- 第 03 组脚注补一句：点标题 / 摘要可打开对应内容；反馈只影响同一关键词下的个人排序。
- 小屏不再隐藏 RAG 的反馈按钮（`.sc-search-hit-meta` 对普通命中仍隐藏）。

### 3.4 已刻意不做

- 不改 `rag_feedback` 唯一键与加权公式，不加「撤销投票」端点（后端无 delete 语义，
  改票靠再次点击相反按钮覆盖）。
- 不做 question_id 深链：需要新增练习页定位参数与后端按 id 取题契约，超出本次范围。
- 不用整行 `<Link>` + 绝对定位按钮：会让键盘焦点与点击目标重叠，维护成本高于收益。

## 4. 验证

- 新增 `src/test/search.test.ts` 5 例：教程锚点、分片后缀去噪、缺 ref_id 降级、
  题目方向 / 子方向、缺项降级。全量 vitest 47 files / 559 tests passed
  （本机 fs shim 的 EPERM 临时目录噪音两条，CI 为准）。
- typecheck / lint / build 全绿；工程门禁 41/41。
- Playwright mock（`backend/logs/tmp-r142/verify_rag_ui.py`）实测：
  - 教程 href `/learn/ch-rag#tutorial-sec-01`、题目 href `/practice?direction=AI+工程&sub=LLM+与+RAG`；
  - `.sc-search-hit-main button` 为 0（按钮不在链接内）；
  - 点「有用」后 `aria-pressed=true`、文案变 `✓ 有用`、状态行出现 `1 赞 / 0 踩`；
  - 请求体 `{query, chunk_id, verdict, surface:'search'}` 正确；
  - 内部 reload 完成后选中态仍在；点标题真实路由跳到教程锚点。
  - 截图 `frontend/logs/tmp-r142/search-rag-feedback.png`。

## 5. 已知边界

- 全页面刷新后本地选中态会消失（后端只存票，未提供「本人对当前 query 的投票」读端点）；
  再次检索同词时排序仍按已存票生效。
- 精排成功时反馈加权不参与排序，按钮仍会记录票，但排序不会因此对本次结果变化。
