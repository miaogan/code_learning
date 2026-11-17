# r118 验收报告（生产实测 2026-11-17）

## 部署链路

| 提交 | 内容 | CI | 生产 deploy-state |
|---|---|---|---|
| `dc3bc97` | compose 新增 `reranker` 服务（1536m 限额） | 全绿 | 2026-11-17T16:37:54+08:00 |
| `978b11b` | 限额修正 1536m → **2g**（见下） | 全绿 | 2026-11-17T17:00 前后 |

## 踩坑：1536m 限额不够

- 症状：容器重启循环（RestartCount 52），日志每次都走到 `Starting model backend` → ONNX 权重就绪 → 静默死亡，`OOMKilled: false / ExitCode 0`（cgroup v2 杀进程的 docker 标记不可靠，别信它）。
- 根因：`onnx/model.onnx` 权重 ~1.1G + ONNX runtime 装载/优化开销，峰值 RSS > 1.5G。
- 修复：`mem_limit 2g / memswap_limit 2560m`。2g 下一次装载成功，warmup 44 秒后 `Ready`。
- 模型下载只发生一次（~1.1G，落 `skillcoach-rerankcache` 卷），此后重启约 1 分钟就绪。

## 冒烟验证（compose 内网，backend 容器发起）

`POST http://reranker:8080/rerank`，query「Docker 容器内存限制怎么配置」，4 条候选：

```
0.9991  Docker 通过 cgroup 与 mem_limit 限制容器内存使用   ← 正确答案断层第一
0.0575  PostgreSQL 的连接池配置建议
0.0010  React 组件使用 useState 管理状态
0.0000  今天天气很好适合出门散步
```

200 / 0.30s（4 条候选）；响应结构 `[{index, score}]` 按 score 降序。

## 内存账（稳态实测）

| 容器 | 占用 |
|---|---|
| reranker | **1.999GiB / 2GiB（99.97%）** |
| backend / embedder / pg / redis / frontend | 105M / 134M / 36M / 3M / 4M |
| 宿主 | used 3.1Gi，available ~511Mi，swap 1.9G 未动 |

## 已知风险与约束（给后续接入精排的需求）

1. reranker RSS 钉在限额上：大批量长文本推理的临时峰值会撞 cgroup 上限 → 容器自愈重启（只影响 reranker 自己）。接入时**候选数应 ≤20、auto-truncate 已开（512 token）**。
2. 宿主 available 只剩 ~500Mi：reranker 是当前最大的常驻占用，机器已接近单机多模型的天花板；后续若再加模型必须先动内存（升配或卸载）。
3. `--max-client-batch-size 32` 可下调为 16 作为进一步保险（未做，当前无压力证据）。
