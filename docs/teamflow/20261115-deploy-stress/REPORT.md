# 部署与三用户并发压测报告（2026-11-15）

> 范围：把 r100–r104（RAG 管线 / Agent 编排 / SSE / 召回反馈 / embedding 容器档）
> 提交并部署到生产（43.166.23.144），随后用 3 个真实账号做并发压测。

## 1. 部署链

| 步骤 | 结果 |
|---|---|
| 提交 | `3744362`（63 文件 / +6805 行），随后两次修复提交 |
| CI（run #138） | ❌ 失败：3 处工程门禁 + 1 处 tiktoken 异常（详见 §4） |
| CI（run #140） | ✅ frontend + backend 双绿（`cc7f6d8`） |
| CD | ✅ `logs/deploy-state` = `cc7f6d8`，四容器 healthy |
| 端点验证 | ✅ `/health` ai_configured=true；`/api/rag/status`、`/api/rag/rebuild`（1284 chunk）、`/api/rag/search`、`/api/evidence/summary`（28 张表）全部 200 |

## 2. 压测结果（3 个独立账号并发）

### 2.1 短时并发（3 用户同时起跑，8 类接口两轮）

| 指标 | 结果 |
|---|---|
| 总请求 | 51（另含 12 个**预期** 404：探测用的不存在 chunk / 任务 id） |
| 耗时 | 3.0s |
| 失败 | **0** |
| 延迟 | 中位 66ms · p95 333ms · 最大 715ms |
| 分接口中位 | me 62 · courses 63 · rag-status 65 · history 66 · evidence 68 · rag-search 174 · feedback 404（预期）· sse-404 62 |

### 2.2 持续并发（60s，按真实节奏 1.4 req/s）

| 指标 | 结果 |
|---|---|
| 请求 | 87，**100% 200** |
| 延迟 | 中位 68ms · p95 318ms · 最大 572ms |
| 服务端 | load 0.01；backend 154MB / PG 51MB / redis 6.5MB / frontend 4.5MB |
| 错误日志 | 期间 **0 个 5xx** |

### 2.3 关于 429（限流器，不是容量问题）

第二轮把节奏加到 2.5 req/s（≈150 次/分）时出现 36 个 429 —— 三个测试账号共用同一个出口 IP，
触发了「120 次/分/IP」的滑动窗口限流。这是**防护按设计工作**：真实三个用户各有独立 IP，
不会互相挤占；报告把这个区分写清楚，避免把限流误读成服务不稳。

## 3. 结论

- 三用户并发在 2 vCPU / 3.6GB 的机器上**无压力**：p95 约 0.3s，全程无 5xx；
- 主要耗时在 `rag/search`（混合检索 174ms，含 DB + 融合），其余接口 60–70ms（多为 HTTPS 往返）；
- 120 次/分/IP 的限流是当前单 IP 压测的上限，不是服务容量上限。

## 4. CI 首轮失败的四处（都已修复，属真实缺陷）

1. `services/coach/agent.py` 出现 `30` 字面量 —— 阈值必须只住 config（门禁 D-1 同类；
   计划时长改为「state 有值才拼」，不再写死默认）。
2. `routers/evidence.py` / `services/retrieval/indexer.py` 直写 SQL —— repository 是唯一出口；
   新增 `repository.public_table_count()` / `question_chunk_rows()`。
3. `test_rag_chunking` 在 CI 抛 `LookupError`：llama `SentenceSplitter` 首次使用要下载 tiktoken
   词表，CI 环境失败 → `_split_prose_llama` 捕获后回退自研句子累加器（分块永不炸链路）。
4. **流程教训**：这些门禁在本地「通过」是因为它们读工作区、而我当时只跑了子集；
   真正跑全量时本地也能复现。CI 现在会把 `FAILED/ERROR` 行输出成 **annotation**，
   匿名即可从 checks API 读到用例名（公开仓库日志下载需要 token）。


## 5. 部署后发现的题库数据异常（历史遗留，非本批引入）

重建索引时报 `written 1348 / stored 1284`，差的 64 条全是 `algo-*`。逐层排查结论：

| 证据 | 结果 |
|---|---|
| `count(*)` / `count(DISTINCT id)` | 1348 / 1284 |
| `pg_index` 的 `questions_pkey` | valid / unique / ready 全为 true |
| `WHERE id='algo-001'`（强制顺序扫描） | 返回 **2 行** |
| `a JOIN b ON a.id=b.id AND a.ctid<>b.ctid` | **64 对**（128 行），ctid 落在页 0 |
| `count(DISTINCT prompt)` | 1284（重复行内容完全相同） |

**判定**：`questions` 表存在 64 对重复 id 行（早期 SQLite→PG 迁移重复导入的历史脏数据，
主键索引状态正常却未拦住）。影响面仅限「索引条数统计虚高」——实际覆盖 1284 道**唯一**题，
**没有真丢题**。

**处置**：索引器已显式按 id 去重（先到先得 + WARNING），保证 `written == stored`；
数据清理（保留每组一行）需要单独决策——`REINDEX TABLE questions` 会直接暴露冲突并失败，
安全做法是先按 ctid 保留每组最小 ctid 的行、再删其余，属于需要停机窗口/备份的运维动作。


## 6. 题库去重与 embedding 切换（同日晚间）

1. **备份**：`scripts/backup_db.sh` → `backups/app-20261115-232851.dump`（804K，`pg_restore -l` 自检通过）。
2. **去重**：`DELETE ... USING ... WHERE a.id=b.id AND a.ctid>b.ctid` → 删除 **77 行**冗余
   （1361 → **1284** 唯一题），`REINDEX TABLE questions` 后索引全部 valid、重复对归零；
   重建索引 `written 1284 == stored 1284`。
3. **embedding 切换**：临时容器 `tei-embed-bench` 删除 → compose `--profile embed` 托管
   （限额生效）→ `backend/.env` 三项（bge-small / `http://embedder:8080/v1` / 512）→
   重建 backend 触发维度自愈 → 重建索引 1284 条 / 97.1s。
4. **效果**：语义腿 recall@5 80% → **95%**，混合 95% → **100%**，MRR 0.858 → 0.925
   （离线基线不变，说明是向量空间的收益）。详见 `docs/eval/RAG-LIVE-REPORT.md`。
5. **切换后并发冒烟**：3 用户 51 请求 0 失败，中位 71ms、p95 222ms；embedder 常驻 155MB。

> 待办：教程正文尚未推送进向量索引（语料只在前端，需在考工页点「推送教程正文」）。
