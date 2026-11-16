# 变更记录

本文件只记录**已部署到生产并验收通过**的版本批次。版本号规则、准入清单与发版步骤见
[`docs/teamflow/20261114-cicd/RELEASE.md`](docs/teamflow/20261114-cicd/RELEASE.md)。

格式：`## [v0.2.0] - 2026-11-16

RAG 检索管线与实时推送（r100–r105），「外包工程师跃迁工作台」从单一练习工具升级为带检索增强与 Agent 编排的完整工作台。

### 新增
- **RAG 检索管线**（r100）：embedding 双档（离线确定性哈希 / OpenAI 兼容远端）、pgvector + HNSW、三态检索（keyword / semantic / hybrid，RRF k=60）、带引用回答；教程语料导出成种子并启动自动摄取（r105，165 小节 → 390 chunk）
- **RAG 自动评审两轨**（r100/r105）：题目轨 + 教程轨金标（20 + 35 例）进 CI 门禁；`--live` 真模型双跑对比；LLM-as-judge 评审轨
- **教练 Agent 编排**（r101）：LangGraph plan → act → reflect → final，4 个只读工具，轨迹可回放（讲席页）
- **实时推送**（r102）：任务进度 SSE + 面试回合流（phase → turn → done），前端流不可用自动回落轮询
- **召回反馈闭环**（r103）：检索结果点赞 / 点踩，投票即时参与本人同查询排序（乘法加权），看板端点就绪
- **工程证据中心**（r100）：考工页行数事实 + RAG 索引状态 + 营造档案
- **本地 embedding 服务**（r104）：compose `embedder` 档（1 核 / 1GB 限额、默认不启动），维度变化自愈迁移

### 修复
- 工程门禁三处违规（30 字面量 / 直写 SQL / tiktoken 异常无兜底）
- `kinds` 过滤下沉到向量检索内部，修「只搜教程 + 长问句」空结果
- 向量索引 ivfflat(lists=100) 对千级数据近似丢结果 → 换 HNSW
- SSE 断连检测在 TestClient 下误报 → 挪到心跳节拍
- 题库 64 对重复 id 行去重（含 REINDEX），rebuild 计数如实

### 数据
- 生产 embedding 已切 `BAAI/bge-small-zh-v1.5`（512 维）：语义腿 recall@5 80% → 95%（+15pp）、混合 95% → 100%

## [vX.Y.Z] - YYYY-MM-DD`，条目按「新增 / 修复 / 运维与安全 / 文档 / 验收」分组。
未发版的内容留在 `dev` 上，不写进本文件；合入 `master` 前由 CI 的 `Release gate`
校验本文件存在对应标题。tag 指向的 commit 即发版时生产实际运行的 `dev` HEAD。

## [v0.1.0] - 2026-11-14

首个受控发布基线。确立 `master`（受保护发布主干）+ `dev`（开发与自动部署）分支模型，
并把 2026-11-14 全天的公网部署成果收编为一个可追溯的版本。

### 新增

- BYOK 国内厂商预设：8 家服务商 + 自定义，设置页可选厂商并自动带出 Base URL 与模型提示。
- GitHub Actions 推 SSH 自动部署：push `dev` → 双门禁 → 受限 deploy key → 服务器部署 / 失败回滚。
- 纯 IP 的 Let's Encrypt 正式证书（SAN `IP Address:43.166.23.144`）+ 每 12 小时自动续期。
- 版本发布流程与 `dev → master` 的 `Release gate` 合入门禁（本版本引入）。

### 修复

- 用户自带 AI「测试连接」把有效 Key 误报为无效：JSON 模式探测语缺 `json` 字样，且 4xx 归因笼统。
- 用户自带 AI 配置的盲 SSRF：拒绝环回 / 内网 / `169.254.169.254`，测试连接超时独立收紧到 8s。
- 部署脚本顶层 `umask 077` 让 checkout 出的源码变 600，进镜像后非 root backend 崩溃、且回滚同样失效。

### 运维与安全

- 公网入口把点文件与备份 / 凭据后缀钉成 404；PG 口令轮换；每日 `pg_dump -Fc` 备份 + 恢复演练。
- 远端分支清理：删除 10 个 dependabot 分支与已停用的 `feat/dev-skill-coach`，只留 `master` + `dev`。
- 证书续期、数据库备份两条 cron 统一 `umask 077`；运行时文件与日志保持 600 / 700。

### 文档

- 公网 443 外部验收报告、CD 可观测性指南、CD 事故复盘（`CD.md` §13）、版本发布规则。

### 验收

- CI `frontend` / `backend` 双门禁全绿；公网 `verify_public.py` **44/44**、0 失败。
- 四容器 healthy、证书链可信、服务器工作树 clean、`deploy-state` 与 `dev` HEAD 一致。
