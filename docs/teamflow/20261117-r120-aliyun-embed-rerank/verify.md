# r120 生产验收报告

时间：2026-11-17 18:53–19:05（UTC+8）｜提交：`012ba15`（CI 双门禁全绿后自动部署）

## 1. 切换动作

| 步骤 | 内容 |
|---|---|
| 配置 | 服务器 `backend/.env`（备份为 `backend/.env.bak.r120`）：`AI_EMBED_*` 指向百炼 compatible-mode（`qwen3.7-text-embedding-flash`，dim 1024，batch 16）；`AI_RERANK_*` 指向 services 原生端点 + `AI_RERANK_PROTOCOL=dashscope` + `AI_RERANK_MODEL=qwen3.7-text-rerank` |
| 停容器 | `docker stop skillcoach-embedder-1 skillcoach-reranker-1`（compose 定义保留在 `--profile embed` / `--profile rerank`，要切回只需重启容器 + 改回 `.env`） |
| 生效 | `up -d --force-recreate backend`（env_file 变化不触发自动重建） |
| 索引 | `init_db()` 检测 dim 512→1024 后清空向量列 → 教程 390 条由启动 seed 自动重建 → 题库 1334 条手动 `rebuild_question_index()` 重建 |

## 2. 内存账（本次最直接的收益）

| | 切换前（r118/r119 常态） | 切换后 |
|---|---|---|
| 宿主 used | 3.1 GiB | **917 MiB** |
| 宿主 available | ~511 MiB | **2.7 GiB** |
| swap | 1.9 GiB（未动，但已无压力） | 1.9 GiB |
| 常驻容器 | backend 123M + embedder 166M + reranker **1.999G** + frontend 8M + PG 40M + redis 5M | backend 123M + frontend 8M + PG 40M + redis 5M |

r118 记录的「这台 3.6G 机器已到顶」解除：现在有约 2.7G 可用，可以再上常驻服务。

## 3. 索引重建

```
{"embedder": "remote:qwen3.7-text-embedding-flash", "dim": 1024, "engine": "pgvector",
 "chunk_count": 1724, "question_chunks": 1334, "tutorial_chunks": 390,
 "stale": false, "written": 1334}
elapsed 115.8s
```

- 1334 题 / 16 条一批 ≈ 84 次云端往返，平均 1.4s/批（含公网 RTT）。
- 教程 390 条在 backend 启动时由 `RAG_SEED_TUTORIALS` 自动重建（日志 `rag.tutorial_seed.done tutorial_chunks=390`）。
- 题库没有自动重建路径（只有考工页手动触发），所以「换 embedder 后必须手动 rebuild 题库」是必须记住的一步。

## 4. 检索验证（生产，真实 HTTP）

`POST /api/rag/search`（登录 cookie 鉴权，demo 账号）：

```
query = "Redis 缓存击穿怎么解决"，mode=hybrid，limit=5
reranked=True  engine=pgvector  total=5  notice=(无)
  0.0156 tutorial  中间件与运维 · 缓存与失效策略 · TTL、淘汰与三类异常
  0.0161 question  研发工程实践 · 架构设计
  0.0152 question  研发工程实践 · 架构设计
  0.0164 question  中间件与运维 · Redis
  0.0154 tutorial  中间件与运维 · 缓存与失效策略 · Cache-Aside 的正确写法
```

三条查询的 service 层耗时（含云端 embedding + rerank 各一次往返）：

| 查询 | 耗时 | 精排 | Top1 |
|---|---|---|---|
| Docker 容器内存限制怎么配置 | 1.04s | ✅ | 容器 OOM 与 limit/request |
| Redis 缓存击穿怎么解决 | 3.11s | ✅ | 缓存与失效策略 · TTL、淘汰与三类异常 |
| MySQL 索引失效的常见原因 | 0.82s | ✅ | SQL 与数据库 · 索引 |

云端 rerank 单独计时（20 条候选，正文截 1200 字）：**0.80s / 2.02s**（两次，公网波动）。
对比 r119 本地 TEI（10 条候选 2.3s）——云端不但更快，还不占内存。

`/health`：

```
{"status":"ok","version":"0.4.0","rag_embedder":"na","db":"postgresql","db_status":"up",
 "redis_status":"up","db_replica":"ready","ai_configured":true}
```

`rag_embedder=na` 是 r120 的新口径：公网端点不探活（此前探 `https://dashscope.aliyuncs.com/compatible-mode/health` 必然 404，会把状态永久报成 down）。

## 5. 已知遗留（本次未改）

1. **精排后 `score` 仍是 RRF 融合分**，与名次不一致（上例 0.0156 排第一、0.0164 排第四）。
   这是 r119 的既有设计（精排只改顺序，不引入它的分数量纲）。前端不展示该字段，API 消费者需知
   排序才是权威。要统一的话，可在精排后用 `1/(k+rank)` 重写 score。
2. **keyword 模式对整句查询 0 命中**：关键词腿是 ILIKE 整串子串匹配（r100 口径），
   「Docker 容器内存限制怎么配置」整句不会命中任何正文。这是既有行为，短关键词才有用。
3. **题库分类问题**：「容器 OOM 与 limit/request」这道题被归在「前端 · css」方向。
   检索和精排都正确召回了它，是种子数据的分类标签错了，属内容侧问题。
4. **compose 里的 embedder / reranker 定义保留**（profile 可选档，默认不启动）。
   将来想切回本地模型：`--profile embed --profile rerank up -d` + `.env` 改回
   `AI_RERANK_PROTOCOL=tei` / `AI_EMBED_BASE_URL=http://embedder:8080/v1` 即可，代码无需改动。

## 6. 回滚路径

```bash
cp ~/skillcoach/backend/.env.bak.r120 ~/skillcoach/backend/.env
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env \
  --profile embed --profile rerank up -d embedder reranker
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env \
  up -d --force-recreate backend
# 再到考工页重建索引（dim 1024→512 同样会清空向量列）
```
