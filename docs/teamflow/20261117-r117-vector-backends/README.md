# r117 向量检索后端：文件型（faiss）+ Milvus，与 `DB_MODE` 同构

- 起始：2026-11-17
- 触发：用户在内网单机部署（无 PG）使用 RAG，要求「像 SQLite 之于 PG 一样，设计一个文件型的
  向量库和一个 Milvus，内网使用文件型的」。
- 结论：新增 `VECTOR_MODE`（`auto` / `pgvector` / `sqlite` / `faiss` / `milvus`），向量检索层
  收拢为唯一分派点 `vector_backends.py`。**元数据的唯一事实源仍是 `rag_chunks`**，faiss /
  Milvus 只是派生索引——换后端不影响任何展示数据，索引坏了 = 重建，不丢数据。

## 1. 选型过程（为什么不是 Chroma）

用户最初选 Chroma。实测后放弃，三条硬理由：

| 检查项 | chromadb 1.5.9 实测 | faiss-cpu 1.16.0 实测 |
|---|---|---|
| wheel 形态 | `cp39-abi3-win_amd64` **23.5MB 平台专属**（核心已 Rust 化） | `cp313-cp313-win_amd64` 16.6MB（同平台问题但体积减半） |
| 运行时依赖 | **28 个**，含 `onnxruntime` / `grpcio` / `kubernetes` / `opentelemetry-api` / `-sdk` / `-exporter-otlp-proto-grpc` | **2 个**（`numpy` + `packaging`） |
| 遥测 | `chromadb.telemetry.product.posthog` **默认开**，历史上连 `us.i.posthog.com`；1.x 目前是 no-op stub，但**这是 chromadb 的打包选择**，升级一个小版本就可能恢复 | 无遥测，无任何出网代码 |

对「不能出现任何遥测」的硬要求，关键不是「能不能关掉」（`ANONYMIZED_TELEMETRY=False` 能关），
而是**保证的层级**：r115 的零遥测守卫（`test_outbound_call_sites_are_registered`）只扫我们自己源码
里的 `httpx` / `requests` 调用，第三方库内部的出网一个字都看不到。引入 Chroma 会把「零遥测」从
**结构级可断言**降级为**相信第三方库的默认值**；镜像里装着 OTLP 导出器 + kubernetes 客户端
（我们两个都用不到），信息安全评审一定要被问「为什么需要它」。

最终：文件型 = **faiss-cpu**（用户拍板），远端 = **pymilvus**（纯 Python 431KB，会带 grpcio / pandas）。
两者都是**可选依赖**，requirements 里 `python_version >= "3.10"` 标记；没装则该档
`ready=False` + 中文提示，`auto` 会跳过它继续探测下一档——与 r103「未装 llama-index 就自研切分兜底」
同一风格。

## 2. 四档语义

| 档位 | 向量存哪 | 相似度在哪算 | `engine` 字段 | 适用 |
|---|---|---|---|---|
| `pgvector` | `rag_chunks.embedding`（`vector(dim)` 或 `double precision[]`） | SQL `<=>` 或取回后 Python | `pgvector` / `python-cosine` | 有 PG 的部署（现状不变） |
| `sqlite` | `rag_chunks.embedding`（JSON 文本） | 取回后 Python 余弦 | `python-cosine` | 内网单机、连 faiss 都不想装 |
| `faiss` | **本地单文件索引**：`<kind>.faiss` + `<kind>.json`（对账） | `IndexIDMap2(IndexFlatIP)`，C++ SIMD | `faiss` | 内网 / 气隙（推荐） |
| `milvus` | 远端 collection | Milvus HNSW `COSINE` | `milvus` | 有向量库服务的企业内网 |

`auto` 展开顺序（`_resolve_auto()`）：

1. 活跃后端是 PostgreSQL → `pgvector`（向量与业务数据同源，还能进 SQLite 副本）；
2. 单机（内网默认形态）装了 faiss → `faiss`；
3. 否则 → `sqlite`（JSON 向量 + Python 余弦，r100/r114 现状）。

显式档位不可用时**启动即报错**：非法值被 `Literal` 校验拦下（`VECTOR_MODE=chroma` 直接
`ValidationError`）；档位合法但依赖缺失 / 地址没填则 `resolve_vector_store()` 返回
`ready=False` + 中文 reason，检索入口与索引状态都把它转成可直接展示的提示。
`VECTOR_MODE` 有专门的 `field_validator` 剥首尾空白——`VECTOR_MODE= faiss` 这种「复制带空格」
必须能启动（r115 的布尔开关踩过同款坑）。

## 3. 关键设计决定

### 3.1 元数据不进向量库

faiss 索引与 Milvus collection **只存 `chunk_id + 向量`（Milvus 另存 kind / embedder 两个过滤列）**，
`title` / `content` 命中后回 `rag_chunks` 取（`repository.rag_fetch_chunks`）。
两个理由：

- 不存在「改了题库解析文案后两份正文漂移」的问题——向量库里根本没有正文；
- 换后端（faiss ↔ milvus ↔ pgvector）不影响任何展示数据。

孤儿 id（索引有、业务库没有）在 `_finalize` 里丢弃并记 warning——宁可少一条，不给空标题。

### 3.2 按 kind 拆文件（faiss）

`kinds` 过滤必须**精确**：先取全局 top-K 再按 kind 筛，会把「只搜教程」变成「教程得先挤进
全局前 K」（`rag_vector_search` 的注释里有同样的教训）。faiss 没法在索引内按元数据过滤，
按 kind 分文件（`question.faiss` / `tutorial.faiss`）是零损失的解；`kinds=None` 时搜全部
已存在的 kind 文件再按分合并。

### 3.3 `IndexFlatIP` 而不是 IVF / HNSW

向量先 L2 归一化，IP 即**精确**余弦——无调参、确定性、可复跑（评测门禁要求逐字节复现），
1.5k 条 × 256 维毫秒级。题库涨到十万级再换 `IndexIVFFlat`，是 `write()` 里的一行改动，
检索层无感。测试里有与手算参照值对齐到 1e-6 的精确性用例。

### 3.4 派生索引的对账（防「元数据齐了、索引没跟上」）

faiss sidecar 记 `(embedder, dim, count, index_sha256, ids)`，加载时逐项校验：

| 对不上 | 行为 |
|---|---|
| embedder 不一致（换过 embedding 模型） | 该文件当不存在 + notice「请重建索引」 |
| dim 不一致 | 同上 |
| `index_sha256` 不匹配（faiss 与 sidecar 不配对，写入中断） | 同上 |
| `count` ≠ 业务库该 kind 行数 | 同上 |

这是 r100 没有的能力：旧口径（只看 `rag_index_state`）会误报健康——「重建到一半进程挂了，
元数据行已提交、faiss 文件没写完」这种状态，检索会静默用旧文件。

### 3.5 写入顺序：元数据先、派生索引后

`write()` 先 `repository.rag_write_chunks(..., replace_kind=kind)`（事务化、幂等、回滚安全），
再写派生索引。派生索引失败会抛错让用户重试，而元数据行的重写是幂等的（`ON CONFLICT` 更新）。
全量替换成空集时删除派生文件，不留「0 向量空索引」冒充已建。

## 4. 与 Milvus 的契约

`MilvusClient(uri, token)` 连内网 standalone（常见 `http://milvus:19530`）：

- collection 默认名 `rag_chunks`，可配 `VECTOR_MILVUS_COLLECTION`（只允许标识符字符，
  因为要拼进 Milvus 的布尔 filter 表达式，非标识符当场拒）；
- 建表：`id`（VARCHAR 主键 = chunk_id）、`kind`、`embedder`、`vector`（FLOAT_VECTOR dim），
  HNSW `COSINE` 索引（M=16，efConstruction=200）；
- 写入：按 kind 删（`kind == "<kind>"`）再插（全量替换语义与其它档一致）；
- 检索：filter = `embedder == "<name>"` [+ `and kind in [...]`]，COSINE 返回相似度（越高越像，
  与 pgvector 的 `1 - distance` 同尺度）。

## 5. 内网 / 气隙部署的最小配置

```bash
# backend/.env
VECTOR_MODE=faiss            # 或 auto（单机 + 装了 faiss 等价）
VECTOR_FAISS_DIR=data/rag-vectors
AI_EMBED_MODEL=              # 留空 = 离线哈希，RAG 全链路零出网
```

离线安装（服务器 linux x86_64，开发机 win_amd64，wheel **按平台分别准备**）：

```bash
pip download faiss-cpu --dest wheels --platform manylinux2014_x86_64 --only-binary=:all:
# 内网机器上：pip install --no-index --find-links wheels faiss-cpu
```

faiss 索引文件在 `data/rag-vectors/`，与 `data/app-fallback.db` 同根——**备份整个 `data/`
目录即可同时带走业务库与向量索引**。索引与业务库的 embedder / 行数对账保证了
「备份的索引配新库」也不会返回错的结果（对不上就提示重建）。

### 5.1 首次部署必须建一次索引（r140 补）

派生索引不在 Git 里，`questions` 表 seed 后 `question.faiss` 并不会自动生成——全新机器
第一次检索报「faiss 索引尚未构建」是**预期状态**，不是故障。三条幂等入口任选其一：

1. **启动自动补建**（r140 起默认开，`RAG_SEED_QUESTIONS=true`）：检测到题库向量不可检索
   就重建一次（`store.has_kind('question')` 精确判定，不靠 notice 字符串匹配）；已建好跳过，
   后端未就绪只留 WARNING 不阻断启动。远程 embedding 部署想省启动时间可设 `false`。
2. **CLI**：`cd backend && python -m app.admin_cli rebuild-index --kind all`
   （`question` / `tutorial` / `all`，全量替换、可重复跑；输出带 vector_mode / embedder）。
3. **考工页**：「重建题库索引」+「推送教程正文」两个按钮，与 CLI 共用同一套 `indexer`。

注意：r117 原设计里 seed 只补教程索引（`tutorial.faiss`），半年后内网部署最常见的
「教程能搜、题库报未构建」正是这个半构建态；r140 的自动补建与 `FaissStore.notice()` 的
按 kind 对照（业务库有 chunk 但磁盘缺文件＝不算健康）一起修掉了它。

## 6. 启动清单（r117 续）

数据层 / 缓存层 / 向量库的决策日志各自回答「**为什么**用它」，用户最先要问的是「**到底**
启用了哪几个库」。启动时在 `[数据层]` / `[缓存层]` 之后统一收口两行：

```
INFO  [启动清单] runtime.components db=sqlite cache=memory vector=faiss
INFO  [启动清单] 说明: 数据库=SQLite 单机库（data/app-fallback.db）；缓存=进程内缓存（未配置 Redis，仅单进程有效）；向量库=faiss（data/rag-vectors）
```

- 一行结构化 key（可 grep / 可告警），一行中文清单（可直接读）；顺序固定 db → cache → vector。
- **向量库未就绪（faiss 没装 / Milvus 地址没填）时两行都是 WARNING** —— 这类配置问题必须
  在启动时可见，不能等到第一次检索才炸。
- Milvus 地址剥掉凭据再打印（URI 可能带 `user:pass@host`），地址本身可以出现，密码不行。

**顺带修掉一个真 bug**：清单上线前的冒烟测试抓到 `resolve_vector_store()` 在 PG 不可达时
会因 `rag_embedding_mode()` 开库连接而抛 `database_unavailable` —— 违反了本模块
「resolve 永不 raise」的第一不变量，且正好发生在启动恢复循环里。修法：pgvector / sqlite 档的
存储形态探测折进 `ready=False`（下一次检索会重新 resolve，自愈）；启动清单本身也逐项兜底，
任何一项探活失败只降级成那一项的说明，绝不打断 `_recover_database` 的重试。

## 7. 验证

- `backend/tests/test_r117_vector_backends.py`（21 项，全零网络）：
  - 配置：闭集钉住、非法值启动期拒绝、带空格容错；
  - 分派：auto 在 PG / 单机下的展开、显式 faiss 缺包、milvus 缺 URI / 非法 collection 名 / 缺包；
  - faiss 真跑：建索引 → 检索命中、engine 如实、kinds 精确过滤、hybrid 融合、
    换 embedder 后文件被跳过、行数不一致对账、空替换删文件、与手算参照值 1e-6 对齐；
  - milvus 契约（假 client 录调用）：先删 kind 再插、插入行形状、filter 表达式、
    collection 未建时返回空。
- 回归：`test_rag_index` / `test_dependency_recovery` / `test_db_standalone` /
  `test_r115_intranet` / `test_r99_ssrf_guard` 114 项全绿；
  `test_dependency_recovery` 里「副本用 JSON 向量服务」那条改为显式
  `VECTOR_MODE=sqlite` 钉住（装了 faiss 后 auto 会分派给 faiss，那条用例要测的是
  sqlite **存储**形态本身）。
- 启动清单：3 项（三组件齐全且 INFO / 向量未就绪升 WARNING 并带原因 / PG 档标签）。
- 后端全量：0 failed / 0 error / 1 skipped。
