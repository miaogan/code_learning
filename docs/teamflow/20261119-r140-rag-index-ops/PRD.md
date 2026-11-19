# r140：内网 RAG 索引开箱可用（自动补建 + 状态诚实 + CLI）

- 日期：2026-11-19
- 发起：用户反馈「我在内网部署，提示我 faiss 索引未构建」。
- 定性：**预期状态叠加三个真缺陷**。faiss 派生索引本就不随题库 seed 自动生成，但①启动链路
  只补教程不补题库、②考工页误报「已构建」与检索页矛盾、③内网部署文档没写建索引这步，
  合起来让用户以为部署坏了。

## 1. 根因

内网单机（`DB_MODE` 留空→SQLite，装了 faiss-cpu）时 `VECTOR_MODE=auto` 会选 faiss 档。
faiss 向量是**派生文件**（`data/rag-vectors/<kind>.faiss` + 对账 `.json`），不在 Git、不随
`questions` seed 生成。启动 `_seed_business_data()` 只做两件事：`question_bank.ensure_seeded()`
（灌题库行）+ `ensure_tutorials_indexed()`（只建 tutorial.faiss）。所以全新机器是
「1334 道题在库里、题库 faiss 文件没有」的半构建态，检索页如实报「faiss 索引尚未构建」。

旧 `index_status()` 的 `built = state is not None or counts["total"] > 0`：教程 seed 写过
`rag_state`、390 条教程 chunk 在 → `built=True`。于是**考工页显示「已构建」、检索页报「未构建」**，
自相矛盾。而 `vector_notice` 虽在 service 里算了出来，却被 `RagStatus` schema 丢弃（Pydantic
默认忽略额外字段），前端也无从展示。

## 2. 改动

### 2.1 状态诚实（契约 + 前端）

- `RagStatus` 新增 `vector_mode` / `vector_engine` / `vector_notice` 三个字段（两个端点
  `/api/rag/status`、`/api/evidence/summary` 都透传）。
- `indexer.index_status()`：`built` 现在还要求派生索引健康（`store.has_kind('question')`），
  「元数据齐、题库 faiss 缺失」如实报 `built=False`；缺索引时补一条中文 `vector_notice`。
- `FaissStore.notice()` 补按 kind 对照：业务库有 chunk 但磁盘缺该 kind 文件＝不健康；旧逻辑
  只遍历磁盘上存在的 kind，所以「tutorial.faiss 在、question.faiss 不在」会被误判健康。
- `VectorStore` 协议新增 `has_kind()`（布尔、无副作用），三档各有实现：db 档看 chunk 计数、
  faiss 看文件+对账+库行数、milvus 保守返回 True（远端写由管理员显式操作，不自动建）。
- 考工页新增「向量后端」行，`索引状态` 用新口径；`vector_notice` 以 warn 条展示，并给出三条
  处理路径（页面按钮 / CLI / 恢复说明）。

### 2.2 启动自动补建

- 新增配置 `RAG_SEED_QUESTIONS`（默认 True，测试置 False）。
- `indexer.ensure_question_indexed(runtime=None)`：`has_kind('question')` 为假且后端就绪时
  调 `rebuild_question_index()` 全量重建；已建则跳过，后端未就绪返回 None（只留 WARNING）。
  **不无条件重建**：远程 embedding 下 1334 题几十秒并消耗配额，内容变化走考工页显式重建。
- `_seed_business_data()` 在题库 seed 之后、教程 seed 之前调用，两种严格档都 best-effort
  （异常只 WARNING，不阻断启动——索引是可选增强，关键词检索仍可用）。

### 2.3 命令行入口

- `python -m app.admin_cli rebuild-index --kind question|tutorial|all`（默认 all），与考工页
  共用 `indexer` 的全量替换实现；输出 engine / vector_mode / embedder / chunk 数与当前状态。
- 加入 `_MUTATING_COMMANDS`：独立进程写完 `rag_chunks` 后必须补 SQLite 副本，否则服务进程
  察觉不到（沿用 admin_cli 既有约定）。

### 2.4 文档

- README 内网章节加「RAG 向量索引」小节：三条建索引入口 + 为什么不是故障 + 备份口径。
- r117 向量后端文档加 §5.1：首次部署必建一次 + 半构建态的来龙去脉。

## 3. 未改动

- 检索口径、RRF 融合、embedding 模型选择、rerank、出网清单（r115 登记制）零改动。
- 教程索引的既有 seed 语义（只在 chunk 为 0 时灌、不覆盖用户推送）不变。
- Milvus 档不自动建索引（远端写要管理员显式决定）。

## 4. 验证

- 后端专项 `test_r140_rag_index_ops.py` 9 例：vector_* 进 schema、半构建态 built=False、
  补建后 built=True 且 notice 清空、两端点透传、幂等、后端未就绪跳过、CLI 三种路径与非法 kind；
  回归 `test_rag_api` / `test_rag_index` / `test_tutorial_seed` / `test_r117` / 工程门禁 41/41 全绿；
  后端全量 **1300 passed / 1 skipped**。
- 前端 typecheck / lint / build 全绿；vitest 本机 EPERM 临时目录噪音（collection 期，非断言失败，
  CI 为准）。
- Playwright（`backend/logs/tmp-r140/verify_evidence_ui.py`，产物 `frontend/logs/tmp-r140/`）：
  半构建态 `索引状态=未构建`、向量后端行显示 faiss、warn 条含「重建题库索引」与 CLI 命令；
  健康态翻「已构建」且 warn 消失——考工页与检索页口径一致。

## 5. 已知边界

- `RAG_SEED_QUESTIONS=true` 时，远程 embedding 部署首次启动会花钱建一次索引；用 `false`
  关掉后改走 CLI 或考工页。离线哈希（内网默认）下即时完成。
- faiss 用当前时区的日键无关；对账仍按 `(embedder, dim, count, index_sha256)` 四元组，
  换 embedding 配置后必须重建（notice 会提示）。
