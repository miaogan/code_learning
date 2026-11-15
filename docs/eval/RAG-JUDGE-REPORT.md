# RAG 生成质量评审报告

> 模式：**DRY-RUN（规则替身，零模型）** ｜ embedder `hash-bigram-256`（engine `pgvector`）｜ 样本量 n = 8
>
> **DRY-RUN 的分数来自规则替身，不证明模型质量**；真实模型评分需 `AI_LIVE=1 python -X utf8 scripts/eval_rag_judge.py --live`。

| 指标 | 值 | 说明 |
| --- | --- | --- |
| 检索覆盖率 | 100.0% | 检索到非空材料的 case 占比 |
| 忠实度均值 | 10.00 / 10 | 答案是否只由引用材料支撑 |
| 相关性均值 | 10.00 / 10 | 答案是否切题且有信息量 |

## 逐组明细

| query | 召回数 | 忠实度 | 相关性 | 引用 |
| --- | --- | --- | --- | --- |
| 用于在组件挂载后 | 3 | 10 | 10 | question:fe-q1 |
| 关于浏览器事件循 | 3 | 10 | 10 | question:fe-q3 |
| 接口的幂等性 | 3 | 10 | 10 | question:be-q3 |
| 中用于创建并切换 | 3 | 10 | 10 | question:cs-q1 |
| 数据库中索引最主 | 3 | 10 | 10 | question:be-q2 |
| 数据库事务的 | 3 | 10 | 10 | question:be-q18 |
| 中把可变对象 | 3 | 10 | 10 | question:be-q6 |
| 风格中资源命名与 | 3 | 10 | 10 | question:be-q20 |
