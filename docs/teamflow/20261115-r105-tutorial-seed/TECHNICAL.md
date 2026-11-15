# r105 · 教程语料导出与启动自动摄取

> 2026-11-15。补掉「教程正文只在浏览器里」的口子：后端现在能离线拿到全量教程语料并自动建索引。

## 1. 问题

RAG 索引分两类 chunk：题库（后端自持）与教程小节（正文只在前端 TS）。此前教程只能靠
「考工」页点「推送教程正文」，意味着：部署新库、离线重建、CI 评测都只能覆盖题库。

## 2. 方案

| 环节 | 做法 |
|---|---|
| 导出 | `scripts/export_tutorials.mjs`：esbuild 打包前端 `lib/ragIngest.ts` → 直接调 `buildTutorialChunks()` → 写 `backend/app/seed/tutorials_rag.json`（165 小节，含 blocks） |
| 新鲜度 | 同一脚本 `--check` 进前端 CI job：重新生成后与仓库文件逐字节比对，不一致即红 |
| 读取 | `services/retrieval/tutorial_seed.py`：解析 + 丢弃缺 `chapter_id`/正文的脏条目 |
| 摄取 | `indexer.ensure_tutorials_indexed()`：**只在 tutorial chunk 为 0 时**调用 `ingest_tutorial_chunks`（整份替换语义，不会半份） |
| 启动 | `main.lifespan` 里 `asyncio.create_task` 后台执行；失败只记 WARNING；关停 cancel |
| 开关 | `RAG_SEED_TUTORIALS=true`（默认）；测试置 false，避免后台任务与计数断言抢写 |

## 3. 为什么不在 Node 里重写切分

切分口径（代码按行、表格重复表头、正文按句、llama/自研双路）只应有一处实现。导出脚本
复用前端同一函数，后端再按 `blocks` 切——**前端负责「语料长什么样」，后端负责「怎么切」**，
两边都不会各长一套逻辑。

## 4. 验证

- `tests/test_tutorial_seed.py`（3 例）：种子可解析且含 blocks；首次摄取 `skipped=False` 且 chunk > 100；
  二次调用 `skipped=True` 条数不变；已有手工推送的 chunk 不被覆盖。
- `node scripts/export_tutorials.mjs --check` 本地通过；后端全量 pytest 通过。
- 生产：部署后启动日志出现 `rag.tutorial_seed.done`，`/api/rag/status` 的 `tutorial_chunks` 从 0 变为非 0。

## 5. 运维

- 改教程后：`cd frontend && node ../scripts/export_tutorials.mjs` → 提交种子（CI 会拦漏导）。
- 想强制重灌教程索引：把教程 chunk 清掉（或 `POST /api/rag/ingest` 推一份）后重启；
  或临时 `RAG_SEED_TUTORIALS=false` 只保留题库索引。
