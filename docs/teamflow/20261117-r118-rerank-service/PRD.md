# r118 · 本地 rerank 精排服务（compose 可选档）

## 背景与结论

r100 检索管线是「双腿召回 + RRF 融合 + 反馈加权重排」，**没有精排层**；`rerank` 在仓库里只作为题库/教程的教学内容出现。生产服务器（2 vCPU / 3.6GB，首尔节点）2026-11-17 实测余量充足（已用 1.1G / 可用 2.5G / swap 1.9G 未动 / 磁盘剩 45G），且 r104 已部署 HF TEI（`text-embeddings-inference:cpu-1.8`）跑 `BAAI/bge-small-zh-v1.5` 做 embedding——TEI 同一镜像换模型即原生支持 `POST /rerank`，因此 rerank 精排走「同镜像再起一个容器」的路径，零新组件。

## 方案

- `docker-compose.yml` 新增 `reranker` 服务：`profiles: ["rerank"]`（默认不启动，与 embedder 的 embed 档同构），模型 `BAAI/bge-reranker-base`（278M 参数交叉编码器，bge-small-zh-v1.5 的配套精排器；large 560M 在本机太重）。
- 资源限额与 embedder 同口径但内存放宽：`cpus 1.0` / `mem_limit 1536m` / `memswap_limit 2g` / `pids_limit 256`——reranker 权重 fp32 ~1.1G，1g 限额会被 cgroup OOM 误杀；加完整机仍留 ~1.2G 余量。
- 模型缓存落命名卷 `skillcoach-rerankcache`（HF_HOME=/data），容器重建不重下；不发布宿主端口，仅 compose 内网可达，公网零暴露。
- 启动方式（生产）：`docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env --profile rerank up -d reranker`。

## 边界与后续

- 本需求**只落容器**，不改后端检索代码：`hybrid.py` 的 RRF 后精排调用（`AI_RERANK_BASE_URL` → `http://reranker:8080`）属下一个需求；届时新增 httpx 内网出网调用须在 `backend/tests/test_r115_intranet.py` 登记。
- 首次启动需从 HF 拉取 ~1.1GB 权重，耗时取决于入网带宽；之后重启不重下。
- 交叉编码器推理比 embedding 重：20~40 候选在单核 CPU 上预计 1~3 秒，作为精排可接受。

## 验收

- [x] `reranker` 服务写入 compose（profile 隔离，默认 `up -d` 不受影响）
- [x] 生产容器启动成功、`/rerank` 冒烟通过、实测内存峰值记录在案（见本目录 `verify.md`）
- [ ] 后端检索管线接入精排（独立需求）
