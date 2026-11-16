# RAG 生成质量评审报告

> 模式：**LIVE（真实模型）** ｜ embedder `hash-bigram-256`（engine `pgvector`）｜ 样本量 n = 20
>

| 指标 | 值 | 说明 |
| --- | --- | --- |
| 检索覆盖率 | 100.0% | 检索到非空材料的 case 占比 |
| 忠实度均值 | 9.05 / 10 | 答案是否只由引用材料支撑 |
| 相关性均值 | 8.80 / 10 | 答案是否切题且有信息量 |

## 逐组明细

| query | 召回数 | 忠实度 | 相关性 | 引用 |
| --- | --- | --- | --- | --- |
| 用于在组件挂载后 | 3 | 10 | 9 | question:fe-q1 |
| 关于浏览器事件循 | 3 | 3 | 6 | question:fe-q3 |
| 接口的幂等性 | 3 | 10 | 9 | question:be-q3 |
| 中用于创建并切换 | 3 | 10 | 10 | question:cs-q1 |
| 数据库中索引最主 | 3 | 10 | 10 | question:be-q2, tutorial:be-db-index:why#1 |
| 数据库事务的 | 3 | 10 | 9 | question:be-q18, question:be-q5 |
| 中把可变对象 | 3 | 10 | 10 | question:be-q6 |
| 风格中资源命名与 | 3 | 10 | 9 | question:be-q20 |
| 镜像与容器 | 3 | 10 | 10 | question:be-q14, tutorial:mw-docker:why#1, tutorial:mw-docker:why#2 |
| 缓存击穿是指大量 | 3 | 10 | 9 | question:l100-036, question:iq380-103 |
| 在一个已排序数组 | 3 | 6 | 7 | question:al-q1, tutorial:algo-hash-pointer:example#1 |
| 栈这种数据结构的 | 3 | 10 | 9 | question:al-q2 |
| 工具接口时 | 3 | 3 | 6 | question:l100-061 |
| 应用进行限流与成 | 3 | 9 | 7 | question:l100-062 |
| 不能处理哪类改动 | 3 | 10 | 10 | question:devprac-002 |
| 会丢弃工作区中尚 | 3 | 10 | 10 | question:devprac-005 |
| 死锁 | 3 | 10 | 9 | question:cs-q11, question:mw-012, question:go-q13 |
| 事务 | 3 | 10 | 9 | question:aieng-042, tutorial:sql-lock-isolation:pitfalls, question:be-q11 |
| 握手 | 3 | 10 | 9 | question:cs-q19, question:tiji-016 |
| 协程 | 3 | 10 | 9 | question:iq380-122, question:be-q15 |
