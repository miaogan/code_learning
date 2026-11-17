# r119 验收报告（生产实测 2026-11-17）

## 部署链路

- 提交 `6b1c77a`（r119 接线）→ CI 全绿 → deploy-state 2026-11-17T17:5x（deploy job 52s）。
- 服务器 `backend/.env` 追加 `AI_RERANK_BASE_URL=http://reranker:8080`（+ TIMEOUT_S=8 / POOL=20），
  `--force-recreate backend` 重建后生效（env_file 变化不触发 compose 自动重建，需显式 recreate）。

## 真实链路验证（生产库 + 生产容器内）

`hybrid.search_chunks('Docker 容器内存限制怎么配置', mode='hybrid', top_k=5)`：

```
耗时 7.12s  reranked=True  engine=pgvector  notice=(无)
0.0164  question  中间件与运维 · Docker 与容器      ← cgroups 资源限制题，正中查询意图
0.0154  question  前端 · css（容器 OOM 与资源 limit）
0.0156  tutorial  计算机基础 · 进程地址空间
0.0149  tutorial  计算机基础 · 页表、TLB
0.0147  tutorial  后端 · Session 与 JWT
```

精排把 Docker/cgroups 语义相关的题目与教程提进前排；`reranked=True` 且 notice 干净
（无失败降级）。

## 延迟账（单机 2 vCPU，1 核给 reranker）

| 环节 | 实测 |
|---|---|
| 精排（10 条真实候选，正文截 1500 字 → 512 token） | **2.26s / 2.29s**（两次） |
| 4 条短候选（r118 冒烟） | 0.30s |
| 全链路（embedder + pgvector + 精排 + 反馈） | ~7s（含首次连接预热） |

语义 / 混合检索的 P95 会从 ~1s 级涨到 ~3-5s 级——这是交叉编码器精排的固有代价，
换来排序质量的显著提升；keyword 模式不受影响。

## 运行约束（沿用 r118 结论）

1. 候选池上限 20（`AI_RERANK_POOL` 钳制），正文 auto-truncate 512 token——reranker
   容器 2g 限额的内存约束。
2. 精排失败 fail-open：降级回融合序 + notice，检索永不因精排 500（单测覆盖三态失败）。
3. 宿主内存 still tight（reranker 常驻 ~2G）：这台机器再加常驻模型前必须先升配或卸载。
