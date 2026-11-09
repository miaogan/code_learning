# M3 检索召回评估报告

> 生成命令：`node scripts/eval_retrieval.mjs` ｜ 数据：`docs/eval/retrieval-gold.json`（version `v1`）｜ 样本量 n = 20
>
> 本报告由 `scripts/eval_retrieval.mjs` 真实运行输出生成，所有数字来自 `searchTutorials` 的实测结果，非手写编造。

## 口径说明

- 评估对象：`frontend/src/lib/tutorialSearch.ts` 的纯函数 `searchTutorials(query, filters, chapters, limit)`，以及 `frontend/src/lib/tutorials.ts` 的 `ALL_TUTORIAL_CHAPTERS`。
- **这是「检索增强」（retrieval-augmented），不是 RAG**：实现与评估全程 **无 embedding、无向量库、无大模型生成**。`searchTutorials` 在小节级文档上做 BM25 关键词召回 + 方向/子方向元数据硬过滤，返回带 `chapter_id` / `section_id` 的 `Citation` 作为引用锚点，不参与任何文本生成。
- 调用方式：对每组标注执行 `searchTutorials(case.query, { direction, sub_direction }, ALL_TUTORIAL_CHAPTERS, 5)`，取 top-5 的 `chapter_id`。
- 指标定义：
  - **recall@5** = top-5 至少命中一个 `expected_chapter_ids` 的组数 / 总组数 n。
  - **无命中拒答率** = 返回空 `citation` 的组数 / 总组数 n。
  - **引用有效率** = 所有返回 `citation` 中 `section_id` 确实存在于对应章节 `sections` 的比例（用 `ALL_TUTORIAL_CHAPTERS` 校验）。
- 数据来源：`docs/eval/retrieval-gold.json`（version `v1`，created_at `2026-11-09`），人工标注，共 20 组。

### 解读限制（不要把 100% 当能力宣传）

- 样本量仅 20 组，且标注查询与教程语料同源（由同一批章节标题启发写成），**存在标注泄漏风险**；recall@5 满分只能证明「实现可用、引用锚点有效」，不能证明对真实用户自由输入的泛化能力。
- 对外引用请使用 Wilson 95% 区间的下界；扩充到 ≥100 组真实用户查询后再更新结论。
- 本评估只覆盖教程侧 BM25，不含题目侧 FTS5，也不含 RRF 融合后的端到端排序。

## 生成命令

在仓库根目录执行：

```bash
node scripts/eval_retrieval.mjs
```

脚本会：① 用 `frontend/node_modules/esbuild` 把两个 TS 模块打包成临时 ESM 并动态导入；② 跑全部标注并计算指标；③ 把指标摘要打印到 stdout；④ 生成/覆写本报告文件。成功运行时退出码 0。

## 样本量与三个指标

| 指标 | 实测值 | 说明 |
| --- | --- | --- |
| 样本量 n | 20 | gold.json 的标注 case 数 |
| recall@5 | 100.0%（20/20） | 点估计；不以裸百分比单独给出，Wilson 区间见下节 |
| 无命中拒答率 | 0.0%（0/20） | 返回空 citation 的组数 / n |
| 引用有效率 | 100.0%（90/90） | section_id 存在于对应章节 sections 的 citation 比例 |

## recall@5 的 Wilson 95% 置信区间

z = 1.96，n = 20，命中组数 k = 20，点估计 p = 1.0000。

```text
denom  = 1 + z^2 / n
center = (p + z^2 / (2n)) / denom
half   = (z / denom) * sqrt( p(1-p)/n + z^2/(4n^2) )
CI     = [center - half, center + half]   （钳到 [0,1]）
```

- Wilson center = 0.9194
- **Wilson 95% CI = [0.8389, 1.0000]，即 [83.9%, 100.0%]**

> recall@5 属于小样本（n=20）比例，故不以裸百分比单独给出，随附 Wilson 区间以反映估计的不确定性。

## 逐组明细

| id | query | 命中章节 | 是否命中 |
| --- | --- | --- | --- |
| r-001 | RAG 引用对不上原文 | ✓ai-rag, ai-finetune-distill | ✅ 命中 |
| r-002 | 多 Agent 转派成环怎么办 | ✓ai-multi-agent, ai-agent-tools, ✓ai-langchain-langgraph | ✅ 命中 |
| r-003 | 推理服务首 token 太慢 | ✓ai-inference-serving | ✅ 命中 |
| r-004 | 提示词改一版效果就崩 | ✓ai-prompt-engineering | ✅ 命中 |
| r-005 | 分不清 token 和微调这些名词 | ✓ai-glossary, ✓ai-llm-basics | ✅ 命中 |
| r-006 | 向量召回总是漏掉关键段落 | ✓ai-rag, ai-finetune-distill, ✓ai-transformer | ✅ 命中 |
| r-007 | React 组件反复重渲染 | ✓fe-react-render | ✅ 命中 |
| r-008 | 事件循环和微任务顺序搞不清 | ✓fe-event-loop | ✅ 命中 |
| r-009 | 接口并发下数据被重复写 | ✓be-concurrency-idempotency, be-db-index, be-http-rest | ✅ 命中 |
| r-010 | 登录态总丢，会话方案没底 | ✓be-auth-session, be-http-rest, be-concurrency-idempotency | ✅ 命中 |
| r-011 | 事务隔离级别和幻读分不清 | ✓sql-lock-isolation | ✅ 命中 |
| r-012 | 多表 join 结果里 NULL 处理错 | ✓sql-join-null, ✓sql-schema-design | ✅ 命中 |
| r-013 | 消息重复投递怎么保证只消费一次 | ✓mw-message-queue | ✅ 命中 |
| r-014 | 缓存和数据库不一致 | ✓mw-cache-strategy | ✅ 命中 |
| r-015 | 动态规划状态转移写不出来 | ✓algo-dp-graph | ✅ 命中 |
| r-016 | 二叉树递归边界老是错 | ✓algo-binary-tree | ✅ 命中 |
| r-017 | TCP 三次握手和 HTTP 关系说不清 | ✓cs-tcp-http | ✅ 命中 |
| r-018 | 进程线程和虚拟内存概念混淆 | ✓cs-memory-virtual, ✓cs-process-thread | ✅ 命中 |
| r-019 | CI 门禁老红，测试分层不会做 | ✓eng-test-ci | ✅ 命中 |
| r-020 | 分支管理和代码评审流程乱 | ✓eng-git-review | ✅ 命中 |

> 「命中章节」列列出该组 top-5 返回的 `chapter_id`（去重保序），前缀 `✓` 表示该章节属于该组 `expected_chapter_ids`；`—` 表示该组未返回任何 citation。「是否命中」为 ✅ 当且仅当至少一个返回 `chapter_id` ∈ `expected_chapter_ids`。
