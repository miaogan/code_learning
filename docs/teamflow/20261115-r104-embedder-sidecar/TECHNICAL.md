# r104 · 本地 embedding 服务（可选容器档）+ 维度变化自愈

> 2026-11-15。用户问「服务器能不能跑小型 embedding」→「能不能放 docker 里限制资源，别影响别的服务」。
> 结论：能，且做成**默认不启动的可选档**——资源硬限额 + 不进默认 `up`，对现有四个服务零影响。

## 1. 服务器实测（43.166.23.144）

| 项 | 实测 |
|---|---|
| CPU | **2 vCPU**，load 0.07 / 0.12 / 0.11 |
| 内存 | 总 3659MB，已用 936MB，**可用 2723MB**，swap 1987MB 未动用 |
| 容器占用 | backend 114MB · postgres 48MB · redis 6MB · frontend 5MB |
| 磁盘 | 59GB，已用 8.7GB（剩 48GB） |
| 外网 | huggingface.co 200 / 34ms；modelscope 302 |

## 2. 容器设计（docker-compose.yml 的 `embedder` 档）

| 维度 | 取值 | 理由 |
|---|---|---|
| 镜像 | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.8` | Rust + CPU 推理，OpenAI 兼容 `/v1/embeddings`，后端 `RemoteEmbedder` 零改动即可指向 |
| 模型 | `${EMBED_MODEL_ID:-BAAI/bge-small-zh-v1.5}`（512 维，~24M 参数） | 2 核 CPU 上查询 ~10–20ms；内存 +250~400MB |
| `profiles: ["embed"]` | 默认 `docker compose up` **不会**启动它 | 没有显式启用时，对现有四容器零影响 |
| `cpus: '1.0'` | 最多 1 核 | 2 核机器留一半给 backend / PG |
| `mem_limit: 1g` / `memswap_limit: 1536m` | 超限 cgroup OOM 只杀自己 | 不允许大量换页拖垮整机 IO |
| `pids_limit: 256` | 防 fork 风暴 | — |
| 端口 | 不发布宿主端口 | 仅 compose 内网，公网零暴露面 |
| 缓存 | 命名卷 `skillcoach-embedcache` + `HF_HOME=/data` | 容器重建不重复下载（模型 ~100MB） |

## 3. 启用前置：维度变化自愈（本轮已实现）

换 bge-small 意味着 `vector(256)` → `vector(512)`；`ADD COLUMN IF NOT EXISTS` **不会**改已有列维度，
切换后插入会直接报 `expected 256 dimensions, not 512`。`_ensure_rag_embedding_column` 现在同时处理：

1. `array → pgvector`（旧镜像 → pgvector 镜像）；
2. **维度变化**（`format_type(atttypid, atttypmod)` 解析出 `vector(512)` 与配置比对）。

两种情况都清空 `rag_chunks` + `rag_index_state` 并按新形态重建列（派生索引本就可整体重建），
`status` 回「未构建」，考工页点「重建题库索引」「推送教程正文」即恢复。
`tests/test_rag_index.py::test_dim_change_wipes_and_rebuilds_column` 钉住。

## 4. 上线步骤（服务器侧，需人工执行）

```bash
# 1) 拉镜像（一次性，约 1–1.5GB；3M 带宽下建议低峰期或走加速源）
cd ~/skillcoach && docker compose pull embedder

# 2) 起 embedder（只这一条不会动现有服务）
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file deploy.env --profile embed up -d embedder

# 3) 确认限额生效 + 探活
docker inspect skillcoach-embedder-1 --format '{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}'
docker exec skillcoach-backend-1 python -c \
  "import httpx; print(httpx.get('http://embedder:8080/health', timeout=5).status_code)"

# 4) 改 backend/.env 指向它（三步一起改，缺一不可）
#    AI_EMBED_MODEL=BAAI/bge-small-zh-v1.5
#    AI_EMBED_BASE_URL=http://embedder:8080/v1
#    AI_EMBED_DIM=512
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file deploy.env up -d backend    # 重启触发 init_db → 清空旧维度索引

# 5) 考工页点「重建题库索引」+「推送教程正文」，然后跑真路径评测
```

## 5. 回退

把 `AI_EMBED_MODEL` 置空（回离线哈希）+ 重启 backend（自动清空 512 维索引、重建 256 维列），
再重建一次索引即可；embedder 容器可随时 `docker compose --profile embed stop embedder`。

## 6. 风险与边界

- **首次拉镜像受 3M 带宽限制**：1–1.5GB 约需 40–70 分钟（一次性）；
- **CPU 抢占**：重建索引期间（1284 题 + 教程）会吃掉约 1 核 1–2 分钟，建议低峰执行；
- **CI 评测仍用离线哈希**（零 Key 可复跑）；真语义模型的质量对比走 `eval_rag.py --live` 单独一条轨，
  不把「能不能跑 CI」和「模型好不好」混为一谈；
- **TEI 无 healthcheck**（镜像内没有 curl/wget 等探针工具），backend 不做 `depends_on`——
  embedder 挂了时 RAG 检索返回中文 notice、重建索引报 AI_UNAVAILABLE，不影响其它功能。

## 7. 真模型对比评测（`eval_rag.py --live`）

用途：**同一金标、同一条管线**，先跑离线哈希基线，再把索引整体换成真模型重跑，
量化「语义腿 80% → ?%」。这是判断「这次升级值不值」的唯一干净口径。

```bash
AI_LIVE=1 \
AI_EMBED_BASE_URL=http://embedder:8080/v1 \
AI_EMBED_MODEL=BAAI/bge-small-zh-v1.5 \
python -X utf8 scripts/eval_rag.py --live
```

- 脚本自己完成切换：**先摘掉 `AI_EMBED_*` 环境变量跑离线基线**（否则两段会变成同一段），
  再探测真实维度（`POST /embeddings` 探针，不猜维度）→ 写 `AI_EMBED_DIM` →
  `init_db` 自动按新维度重建列 → 重建索引 → 重跑三态。
- 产出 `docs/eval/RAG-LIVE-REPORT.md`：三态 recall/MRR/hit@1 的**前后对比 + Δ**、
  逐组命中名次（前 → 后）、以及「金标是子串式标注，应重点看 semantic 腿与 MRR」的解读限制。
  离线基线报告（`RAG-RETRIEVAL-REPORT.md`）不被覆盖。
- 门禁：live 段同样过「hybrid ≥ 70% 且不比 keyword 回退超 5pp」；不通过则退出 1。
- **三道守卫**（`tests/test_eval_rag_guards.py` 钉住）：无 `AI_LIVE=1` → 2；`--check` 与
  `--live` 互斥 → 2；`AI_LIVE=1` 但缺端点配置 → 连库之前就退出 2。

**验证方式**：本轮用一次性假 OpenAI 兼容端点（128 维确定性向量，不进仓库）端到端跑通
「探针 → 切模型 → 重建索引 → 双跑对比 → 报告」，确认链路与守卫都按预期工作；
**假端点产出的报告已删除**——真数字要等服务器上真模型跑出来，不能用假数据充数。

## 8. 服务器实测（2026-11-15，临时 `docker run` 验证，限额与 compose 档一致）

| 项 | 实测 |
|---|---|
| 镜像 | `text-embeddings-inference:cpu-1.8`（938MB） |
| 模型 | `BAAI/bge-small-zh-v1.5` —— **官方仓库没有 ONNX**，TEI 1.8 自动退到 candle + safetensors 后端，正常出向量（512 维） |
| 单条查询 | 中位 **19.4ms**、均值 19.7ms（含 HTTP 开销，容器内测量） |
| 批量 | 32 条 **356ms**（约 90 条/秒）；日志里的 `max_batch_requests=4` 指**并发请求数**，不影响单请求的输入条数 |
| 全量重建 | 1284 条 **39.0s**（33 条/秒）——比预估的 1–2 分钟更快，题库 + 教程一次重建 < 1 分钟 |
| 常驻内存 | **131MB**（限额 1GB）；系统可用内存从 2723MB → 2599MB |
| 空闲 CPU | 0.34%（限额 1.0 核，实测几乎不吃） |
| 限额生效 | `NanoCpus=1000000000 / Memory=1GiB / MemorySwap=1536MiB / PidsLimit=256` 逐一核对通过 |
| 镜像拉取 | 1 分钟级（ghcr 可达，200/38ms；比预估的 40–70 分钟快得多） |

**结论**：这台 2C/3.6G 的机器跑 bge-small **绰绰有余**——查询 20ms、重建 40s、常驻 131MB，
且限额下最多只占 1 核 / 1GB。

**部署现状**：容器以 `docker run` 临时起（命名 `tei-embed-bench`，挂在 `skillcoach_default` 网络，
模型缓存落 `skillcoach-embedcache` 卷）。生产 compose 里还没有这个服务定义——**新代码（r100–r104）
尚未部署**，所以 RAG 端点与维度自愈都还不在线上。等新代码随 CD 上线后：
`docker rm -f tei-embed-bench` → `docker compose --profile embed up -d embedder` 交由 compose 托管。
