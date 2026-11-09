# 题目侧 FTS5 检索召回评估报告

> 生成命令：`python -X utf8 scripts/eval_question_retrieval.py` ｜ 数据：`docs/eval/question-retrieval-gold.json`（version `v1`）｜ 样本量 n = 20
>
> 本报告由 `scripts/eval_question_retrieval.py` 真实运行输出生成，所有数字来自本次内存库 FTS5 检索的实测结果，非手写编造。
> 数据全部为合成 / 题库启发标注，仅用于回归检测，不是能力宣传。

## 口径说明

- 评估对象：SQLite `question_search` FTS5 trigram 虚表上的题目关键词召回。
- **这是关键词检索，不是向量检索 / RAG**：全程无 embedding、无向量库、无大模型生成；MATCH 是短语匹配，返回题目 id 作为引用锚点，不参与任何文本生成。
- 复现方式：在内存库从 `backend/app/seed/questions.json` 读题目，建 `questions` 表与 `question_search` FTS5 trigram 虚表，灌入 prompt / explanation / direction / sub_direction。
- 检索逻辑与 `repository.search_questions()` 完全一致：把 needle 用双引号包成短语做 FTS5 MATCH（内部双引号翻倍转义），按 bm25 升序取 top-5；query 长度 < 3 时降级 LIKE。
- 不启用方向硬过滤（等价于以默认参数调用 search_questions），case 的 direction 仅作标注元信息与方向覆盖统计。
- 指标定义：
  - **recall@5** = top-5 至少命中一个 `expected_question_ids` 的组数 / n。
  - **无命中率** = top-5 返回为空（未召回任何题目）的组数 / n；未命中期望 = 1 - recall@5。
  - **FTS5 命中占比** = 走 FTS5 路径且命中期望的组数 / n。
  - **Wilson 95% 区间** = 对 recall@5 的小样本比例区间（z=1.96）。
- 数据来源：`docs/eval/question-retrieval-gold.json`（version `v1`，created_at `2026-11-09`），共 20 组，覆盖 8 个方向，期望 id 100% 来自题库真实 id。

### 解读限制（不要把 100% 当能力宣传）

- 标注集由题目关键词启发写成（query 取自题干连续中文子串或 2 字概念词），**存在标注泄漏风险**；recall@5 高分只能证明「FTS5 索引重建、MATCH 转义与 LIKE 降级逻辑未回归、引用 id 有效」，不能证明对真实用户自由输入的泛化能力。
- 本评估只用于 CI 回归检测，不是能力宣传；数据全部为合成 / 题库启发标注。
- 对外引用请使用 Wilson 95% 区间的下界；扩充到 >=100 组真实用户查询后再更新结论。
- 本评估只覆盖题目侧 FTS5 关键词召回，不含向量检索 / RAG / RRF 融合后的排序。

## 生成命令

在仓库根目录执行（Windows 请用 `python -X utf8`）：

```bash
python -X utf8 scripts/eval_question_retrieval.py
python -X utf8 scripts/eval_question_retrieval.py --check
```

- 默认模式：重建内存索引、跑全部标注、打印摘要并生成/覆写本报告，退出 0。
- `--check`：只读，只算指标并打印，绝不写任何文件；门禁 recall@5 >= 70%，满足退出 0，否则打印中文失败原因并退出 1。
- 仅依赖 Python 标准库（sqlite3 / json / math / pathlib / argparse），零网络、零 FastAPI 依赖；本机 SQLite 缺 FTS5 或 trigram 时明确失败退出 2。

## 样本量与指标

| 指标 | 实测值 | 说明 |
| --- | --- | --- |
| 样本量 n | 20 | gold.json 的标注 case 数，覆盖 8 个方向 |
| recall@5 | 100.0%（20/20） | top-5 命中任一期望 id 的组数 / n |
| 无命中率 | 0.0%（0/20） | top-5 返回为空的组数 / n |
| FTS5 命中占比 | 80.0%（16/20） | 走 FTS5 路径且命中期望的组数 / n |
| recall@5 Wilson 95% 区间 | [83.9%, 100.0%] | z=1.96 的 Wilson score 区间 |

## recall@5 的 Wilson 95% 置信区间

z = 1.96，n = 20，命中组数 k = 20，点估计 p = 1.0000。

```text
denom  = 1 + z^2 / n
center = (p + z^2 / (2n)) / denom
half   = (z / denom) * sqrt( p(1-p)/n + z^2/(4n^2) )
CI     = [center - half, center + half]   （钳到 [0,1]）
```

- **Wilson 95% CI = [0.8389, 1.0000]，即 [83.9%, 100.0%]**

> recall@5 属于小样本（n=20）比例，故不以裸百分比单独给出，随附 Wilson 区间以反映估计的不确定性。

## 检索路径分布（FTS5 / LIKE 降级）

- FTS5 MATCH 路径：16 组，其中命中期望 16 组。
- 短查询降级 LIKE 路径：4 组（query 长度 < 3，按 id 排序、无 bm25 相关性排序，是已知局限）。
- 本标注集 20 组中 16 组走 FTS5、4 组走 LIKE，两条路径均实测覆盖。

## 逐组明细

| id | query | 方向 | 检索路径 | top-5 返回（命中期望加 [期望] 前缀） | 是否命中 |
| --- | --- | --- | --- | --- | --- |
| q-001 | 用于在组件挂载后 | 前端 | fts5 | [期望]fe-q1 | 命中 |
| q-002 | 关于浏览器事件循 | 前端 | fts5 | [期望]fe-q3 | 命中 |
| q-003 | 接口的幂等性 | 计算机基础 | fts5 | [期望]be-q3 | 命中 |
| q-004 | 中用于创建并切换 | 计算机基础 | fts5 | [期望]cs-q1 | 命中 |
| q-005 | 数据库中索引最主 | SQL 与数据库 | fts5 | [期望]be-q2 | 命中 |
| q-006 | 数据库事务的 | SQL 与数据库 | fts5 | [期望]be-q5, be-q18 | 命中 |
| q-007 | 中把可变对象 | 后端 | fts5 | [期望]be-q6 | 命中 |
| q-008 | 风格中资源命名与 | 后端 | fts5 | [期望]be-q20 | 命中 |
| q-009 | 镜像与容器 | 中间件与运维 | fts5 | [期望]be-q14 | 命中 |
| q-010 | 缓存击穿是指大量 | 中间件与运维 | fts5 | [期望]l100-036 | 命中 |
| q-011 | 在一个已排序数组 | 算法与数据结构 | fts5 | [期望]al-q1 | 命中 |
| q-012 | 栈这种数据结构的 | 算法与数据结构 | fts5 | [期望]al-q2 | 命中 |
| q-013 | 工具接口时 | AI 工程 | fts5 | [期望]l100-061 | 命中 |
| q-014 | 应用进行限流与成 | AI 工程 | fts5 | [期望]l100-062 | 命中 |
| q-015 | 不能处理哪类改动 | 研发工程实践 | fts5 | [期望]devprac-002 | 命中 |
| q-016 | 会丢弃工作区中尚 | 研发工程实践 | fts5 | [期望]devprac-005 | 命中 |
| q-017 | 死锁 | 计算机基础 | like | [期望]cs-q11, go-q13, iq380-158, iq380-182, l100-047 | 命中 |
| q-018 | 事务 | SQL 与数据库 | like | aieng-042, be-q11, be-q12, [期望]be-q18, be-q5 | 命中 |
| q-019 | 握手 | 计算机基础 | like | cs-q19, [期望]cs-q3, cs-q6, mw-036, tiji-016 | 命中 |
| q-020 | 协程 | 后端 | like | [期望]be-q15, go-q17, iq380-121, iq380-122, iq380-124 | 命中 |

> 「top-5 返回」列列出该组检索返回的题目 id（保序），前缀 [期望] 表示该 id 属于该组 `expected_question_ids`；`—` 表示未返回任何题目。
> 「是否命中」为「命中」当且仅当至少一个返回 id 属于期望集合；检索路径 `fts5` 表示走 FTS5 MATCH，`like` 表示短查询降级。
