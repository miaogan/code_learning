# r121 生产验收

提交 `e7b5d00`，CI 双门禁全绿后自动部署（backend 容器 11:43:07 UTC 重建）。

## 修复前后对照（同一台生产、同一批数据）

**修复前**（r120 验收记录，`score` 是 RRF 融合分）：

```
0.0156 tutorial  TTL、淘汰与三类异常     ← 第 1 名
0.0161 question  研发工程实践 · 架构设计
0.0152 question  研发工程实践 · 架构设计
0.0164 question  中间件与运维 · Redis    ← 第 4 名，分数最高（矛盾）
```

**修复后**（`score` 是精排相关性分，严格递减）：

| 查询「Redis 缓存击穿怎么解决」 | score |
|---|---|
| tutorial 缓存与失效策略 · TTL、淘汰与三类异常 | **0.9553** |
| question 研发工程实践 · 架构设计 | 0.9478 |
| question 研发工程实践 · 架构设计 | 0.7706 |
| question 中间件与运维 · Redis | 0.7052 |
| tutorial 缓存与失效策略 · Cache-Aside 的正确写法 | 0.6753 |

| 查询「Docker 容器内存限制怎么配置」 | score |
|---|---|
| question 容器 OOM 与 limit/request | **0.7933** |
| question Docker 与容器 | 0.7752 |
| question Docker 与容器 | 0.4295 |
| tutorial 镜像与容器 | 0.3057 |
| tutorial 镜像与容器 | 0.1871 |

- 分数全部落在 (0, 1)，且与排名严格单调——「第 1 名分数最高」恢复了。
- 排序结果与修复前完全一致（只改分数，不改顺序）。
- 耗时 2.62~3.40s，与 r120 持平（精排调用次数未变）。

## 口径变化需知

- `reranked=true` 时 `score` 从 ~0.016（RRF）变成 0~1（精排分）。前端不渲染该字段，UI 无变化。
- `reranked=false`（未配置精排 / fail-open / keyword 模式）时分数口径**完全不变**：
  keyword 恒 1.0、semantic 余弦、hybrid RRF。此时排序依据确实是这些分，口径自洽。
- 精排用的是 `qwen3.7-text-rerank` 的 `relevance_score`，文档口径即 [0,1]，原值透传；
  若将来切回 TEI 自建容器，其 logit 会被 sigmoid 映射到 (0,1)，调用方无需感知。

## 遗留

- r120 报告里的另外三条遗留与本次无关：keyword 整句 0 命中（r100 既有）、
  一道容器题分到「前端 · css」方向（种子数据分类错）、compose 里本地模型容器定义保留。
