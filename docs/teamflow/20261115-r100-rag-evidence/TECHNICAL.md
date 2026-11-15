# r100 · RAG 检索管线 + 自动评审 + 工程证据中心（考工）

> 2026-11-15。触发：全功能审计结论「工程深度被低估（不可见）、AI 深度是真短板（无 RAG / 无向量检索）」。
> 本批交付三件事：A 工程证据中心（让已有深度可见）、B1 RAG 检索管线（embedding → pgvector → RRF 融合）、
> B2 RAG 自动评审（检索三态评测门禁 + LLM-as-judge）。

## 1. 交付物清单

### B1 RAG 检索管线（后端）

| 层 | 文件 | 要点 |
|---|---|---|
| 配置 | `backend/app/core/config.py` | 新增 embedding 档位：`AI_EMBED_MODEL`（空 = 离线 HashingEmbedder）/ `AI_EMBED_BASE_URL` / `AI_EMBED_API_KEY`（留空继承主档）/ `AI_EMBED_TIMEOUT_S=60` / `AI_EMBED_DIM=256`（**进 DDL**）/ `AI_EMBED_BATCH=32` |
| embedding | `backend/app/services/retrieval/embeddings.py` | `HashingEmbedder`：char-bigram + `zlib.crc32` 特征哈希（跨进程稳定，刻意不用内建 `hash()`——PYTHONHASHSEED 会变）；`RemoteEmbedder`：OpenAI 兼容 `/embeddings`，批量 + 维度断言；`resolve_embedder()` 解析永不 raise |
| 存储 | `backend/app/core/db.py` | `rag_chunks`（chunk 共享语料，无 user_id，与 `questions` 同口径；`UNIQUE(kind, ref_id, section_id)` 幂等锚点）+ `rag_index_state`（单行索引快照）；`CREATE EXTENSION vector` 尽力创建（独立连接，失败只记日志——与 pg_trgm 同模式）；embedding 列按扩展可用性分支为 `vector(dim)`（ivfflat 余弦索引）或 `double precision[]`（降级） |
| 数据访问 | `backend/app/core/repository.py` | `rag_write_chunks`（全量替换语义 + 维度断言 + `::vector` 字面量唯一出处）、`rag_vector_search`（索引内 `<=>` 余弦）、`rag_array_scan` + `rag_cosine`（降级腿）、`rag_lexical_search`（ILIKE 关键词腿）、`rag_state_get/put`、`rag_embedder_breakdown`（stale 判定）、`evidence_data_scale` |
| 索引构建 | `backend/app/services/retrieval/indexer.py` | 题库重建（**answer 刻意不进索引**）与教程整份摄取都是**全量替换**——增量 diff 依赖「主键永不复用」并不成立（adopt / question_merge 会改行）；`content_sha = sha256(embedder+NUL+content)`，换模型自然失效 |
| 检索 | `backend/app/services/retrieval/hybrid.py` | mode 闭集 `keyword | semantic | hybrid` 唯一出处；hybrid = 两腿各自 top-K 后 **RRF（k=60，Cormack 2009 原论文值）**——只看名次不看原始分，免疫向量余弦与 ILIKE 命中的量纲不可比；未建索引 / embedder 不一致时返回空集 + 中文 notice，不 500 |
| 生成 + 评审 | `backend/app/services/retrieval/answer.py` | `generate_answer`：材料编号（m1..mN）→ 答案 + citations；**引用白名单**：m<n> 映射回 chunk_id，越界引用丢弃并计 `dropped_citations`（与画像 source_quote 同一反幻觉纪律）；`judge_answer`：LLM-as-judge（faithfulness / relevance 0-10），供评测脚本复用 |
| 端点 | `backend/app/routers/rag.py` | `GET /api/rag/status`、`POST /api/rag/rebuild`、`POST /api/rag/ingest`、`POST /api/rag/search`、`POST /api/rag/answer`（answer 走 `user_ai.client_for(user, "light")`，能力档与教练一致） |
| 契约 | `backend/app/schemas.py` | `RagStatus / RagRebuildResult / RagIngestItem / RagIngestRequest / RagChunkItem / RagSearchRequest / RagSearchResponse / RagAnswerDraft / RagAnswerRequest / RagAnswerResponse / RagJudgeDraft / EvidenceSummary` |

### B2 RAG 自动评审

| 轨道 | 文件 | 门禁口径 |
|---|---|---|
| 检索轨 | `scripts/eval_rag.py` | 金标复用 `docs/eval/question-retrieval-gold.json`；三态对比 recall@5 / MRR@5 / hit@1；`--check` 门禁：**hybrid recall@5 ≥ 70% 且不比 keyword 回退超过 5 个百分点**（融合的意义是「至少不比单腿差」）；产出 `docs/eval/RAG-RETRIEVAL-REPORT.md` |
| 生成轨 | `scripts/eval_rag_judge.py` | LLM-as-judge：默认 DRY-RUN（规则替身，验证检索→引用→评分→聚合管线，零网络零 Key，`--check` 进 CI）；`--live` 需 `AI_LIVE=1`（真实模型两跳：生成 + 评审），产出 `docs/eval/RAG-JUDGE-REPORT.md`，如实标注 DRY-RUN / LIVE |
| 共享件 | `scripts/scripts_eval_shared.py` | 评测库准备（建库 → 重建 schema → init_db → 灌题库 → 重建 RAG 索引），两个脚本同一口径 |

### A 工程证据中心（考工）

| 端 | 文件 | 要点 |
|---|---|---|
| 后端 | `backend/app/routers/evidence.py` + `repository.evidence_data_scale()` | `GET /api/evidence/summary`：单次往返取全组计数（题库全量、业务表按账号隔离）、表数、RAG 状态——零 AI、零评分 |
| 前端 | `frontend/src/pages/EvidencePage.tsx`（路由 `/evidence`，侧栏「设置」组「考工」） | 实时证据（行数事实）→ RAG 索引状态与**重建 / 推送按钮** → 营造档案（静态工程卡片：幂等三件套 / 迁移 / RAG / 自动评审 / 可靠性 / CD） |
| 前端 | `frontend/src/content/engineeringArchive.ts` | 静态档案单点维护；活数字（表数 / chunk 数）刻意不写死，全部来自后端聚合 |
| 前端 | `frontend/src/lib/ragIngest.ts` | 教程 blocks → chunk 序列化 → 整份推送（与后端全量替换语义配套） |
| 前端 | `frontend/src/pages/SearchPage.tsx` | 新增「03 / RAG 向量混合检索」区：混合 / 语义两模式切换，展示 chunk 命中 + 引擎形态（pgvector / Python 余弦降级）如实标注 |

### 基础设施

- `docker-compose.yml` 与 CI services：`postgres:16-alpine` → **`pgvector/pgvector:pg16`**（PostgreSQL 16 基线不变）。
- CI 新增两道门禁：`eval_rag.py --check`、`eval_rag_judge.py --check`（backend job，连真库）。
- `backend/.env.example` 新增 embedding 档位示例；`tests/conftest.py` 的 `_NEUTRAL_AI_ENV` 补 `AI_EMBED_*` 三键（宿主配了远端 embedding 也不让测试出网）。

## 2. 关键设计决策（为什么这么做）

1. **默认离线确定性 embedding 而不是必配模型**：评测门禁的可复跑性是硬约束——HashingEmbedder
   让 CI 零 Key、零网络、逐字节复跑；它的「语义」是字符 bigram 重叠（模糊关键词基座），
   报告与状态页都如实标注，不冒充语义模型。接真实语义模型只改 `.env`，管线零改动。
2. **RRF 而非分数加权融合**：向量余弦 ∈ [-1,1]、ILIKE 命中恒 1.0，量纲不可比；
   RRF 只看名次，天然免疫两套分数的分布漂移，是「不调参的融合」。
3. **全量替换而非增量 diff**：题库行会被 adopt / question_merge 改写，diff 的正确性依赖
   「主键永不复用」这一不成立的前提；1284 题 + 教程小节的全量重建在离线哈希下毫秒级。
4. **embedding 列类型按扩展可用性分支**：pgvector 缺席时降级为 `double precision[]` +
   取回后 Python 余弦，`engine` 字段如实报告降级形态——与 pg_trgm 的降级纪律同一模式。
5. **stale 检测**：`rag_embedder_breakdown` 按行统计各 embedder 的 chunk；换 embedding 配置后
   status 亮 `stale=true` + 中文提示「请重建」，而不是让旧向量静默退出检索被当成全量生效。
6. **dim 进 DDL**：`vector(dim)` 列类型绑定维度，插入前逐条断言，错维向量即中文报错
   ——错维余弦是噪声排序，比报错更糟。

## 3. 验证状态

| 项 | 状态 |
|---|---|
| ruff（app + tests） | ✅ 全绿（本机实跑） |
| 前端 typecheck / lint / test / build | ✅ 全绿（本机实跑；build 需把 TEMP 指到工作区目录，沙箱临时目录无权限属环境噪声） |
| 后端 pytest 全量（PG 真库 5433，无 pgvector → array 降级路径） | ✅ 全部通过（含 22 个 RAG 新用例；两轮：初版修复种子题断言后重跑） |
| 后端 RAG 测试（PG18 + pgvector 0.8.1 真路径，5435） | ✅ 22/22 通过：`vector(dim)` 列 + ivfflat + `<=>` 索引内余弦全链路实测 |
| `eval_rag.py --check` / `--live 报告` | ✅ 门禁通过（hybrid recall@5 95% ≥ 70%，且未比 keyword 100% 回退超 5pp；报告 `docs/eval/RAG-RETRIEVAL-REPORT.md`，engine=pgvector） |
| `eval_rag_judge.py --check` / 报告 | ✅ 门禁通过（DRY-RUN：检索覆盖率 100%，引用合法；报告 `docs/eval/RAG-JUDGE-REPORT.md`） |
| 冒烟（零 DB） | ✅ HashingEmbedder 确定性 / 主题区分度（同题 0.71、跨题 0.0）、RRF 双腿命中者第一 |

> 三态实测（hash-bigram-256，n=20，金标为题干子串式标注）：keyword recall@5 100% / MRR 0.9125；
> semantic 80% / 0.6533；hybrid 95% / 0.8583。语义腿在子串式金标上天然弱于关键词腿（字符 bigram
> 的诚实边界），融合把两腿拉回 95% 且没有拖垮关键词腿——这正是 RRF 门禁设计要的形态。

### 3.1 验证期间发现并修复的缺陷

1. **`rag_embedding_mode()` 判型 bug（严重）**：原实现查 `information_schema.columns.data_type`
   并判 `== "vector"`——但 information_schema 对用户自定义类型一律报 `'USER-DEFINED'`，
   pgvector 列也如此，判型**永远失败**，生产 pgvector 库会永远走 Python 余弦降级、绕过 `<=>`
   索引。修复：改查 `udt_name`（pgvector 列 = `'vector'`，double precision[] = `'_float8'`）。
   在真 pgvector 实例上验证 `engine=pgvector` + 22 用例重跑全绿后才算修完。
2. **评测脚本 `_metrics` 键名笔误**：`case["expected_question_ids"]` 应为重建后的
   `case["expected"]`（KeyError → 退出 2，门禁按「运行失败」显式红掉，未静默）。
3. **种子题污染断言**：`test_rag_api.py` 最初按「只有本页插入的 2 道题」断言，但 TestClient
   的 lifespan 启动即幂等灌入完整种子题库（1284 道）——把计数断言改成「≥ 插入数」、
   召回断言改成「插入的题必须在结果里」。
4. **pgvector 镜像拉取**：直连 Docker Hub 长时间无进展，最终经 1ms.run 加速源拉取成功
   （`docker.1ms.run` 前缀拉取后 `docker tag` 回官方标签）。拉取期间真路径验证改用本地
   `postgres:18-alpine` + `apk add postgresql-pgvector` + 扩展目录桥接起临时实例完成。
   **栈切换已执行**：`docker compose up -d postgres` 用 pgvector 镜像重建容器（数据卷无恙、
   backend 连接池自动重连、/health 全绿），并在此真实升级路径上验证了 **array→pgvector
   自愈迁移**（见 §3.2）。

### 3.2 array → pgvector 引擎升级自愈（栈切换时补的迁移缺口）

存量库的 `rag_chunks.embedding` 若是在无 pgvector 时代建的（`double precision[]`），
装上扩展后 `ADD COLUMN IF NOT EXISTS` **不会改已有列类型**——旧列永远挡住 `<=>` 索引路径。
`_ensure_rag_embedding_column` 自愈：`init_db()` 探到「vector 扩展可用 且 列 udt ≠ vector」
时清空 `rag_chunks` + `rag_index_state`（派生索引本就可整体重建；`float8[]` 字面量 `{...}`
与 pgvector 的 `[...]` 格式互斥、无无损转换），按 `vector(dim)` 重建列，status 回「未构建」，
重建索引即得快路径。`test_engine_upgrade_wipes_and_rebuilds_column` 在独立库上复现
「降级建列 → 灌数据 → 装扩展 → 再 init_db」全程；线上栈实测：sc_test 旧 array 列自愈为
`vector`，全量 pytest 连续两轮 100%（首轮容器刚重建出现过 1 例偶发 F，复跑两轮全绿），
两道 RAG 门禁在切换后的栈上复跑通过。

## 4. 后续（未在本批交付）

- B3 面试流式化（SSE 逐字 + 任务进度推送替代 2s 轮询）
- B4 教练 Agent 编排深化（规划器调度工具：语义检索 / 出题 / 判分 / 调整计划）
- 教程摄取自动化（当前需在考工页手动点「推送教程正文」；可随题库种子一起在启动期做）
