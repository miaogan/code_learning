# 变更记录

本文件只记录**已部署到生产并验收通过**的版本批次。版本号规则、准入清单与发版步骤见
[`docs/teamflow/20261114-cicd/RELEASE.md`](docs/teamflow/20261114-cicd/RELEASE.md)。

条目格式：`## [vX.Y.Z] - YYYY-MM-DD`，按「新增 / 修复 / 运维与安全 / 文档 / 验收」分组。
未发版的内容留在 `dev` 上，不写进本文件；合入 `master` 前由 CI 的 `Release gate`
校验本文件存在对应标题。tag 指向的 commit 即发版时生产实际运行的 `dev` HEAD。

## [v0.4.0] - 2026-11-16

岗位闭环：从「我该练什么」到「这份 JD 要什么、我有什么证据、差在哪、下场怎么练、报告怎么回收」。全部零 AI 新增、零新表、零分数。

### 新增
- **跃迁档案** `/leap` + `GET /api/leap-archive`：一次聚合目标岗位差距（复用报告已算好的 `role_fit`）、项目工程证据（画像 bullets + 溯源条数 + 站内规模事实 + RAG / 雷达状态）、面试表达（最近 5 场已评分发言 + 「问题—方案—指标—踩坑」文本自检）；服务端零 AI、零新表、零重算，前端零二次统计。教练 Agent 新增只读工具 `read_leap_archive`，太傅页面上下文白名单加入 `/leap`
- **JD 岗位对位** `/jd` + `POST /api/jd-match`：粘贴 JD 后返回技术词三态（有证据 / 证据弱 / 未找到证据）、JD 原句与简历证据引用；缺口严格区分 `origin=jd`（JD 写到但画像无证据）与 `origin=role_model`（岗位模型要求但 JD 未直接写）；按本次岗位现场对标，不改已写入的医案报告；不产出匹配分或百分比
- **缺口驱动定向追问**：`InterviewSettings.focus_gaps`（≤3，统一清洗）落本场 settings 且永不写回画像；开局提示词要求前 `min(3,N)` 道 technical 围绕缺口、追问沿缺口深挖不换题；`/jd` → `?focus=` → 召对表单全链路可带
- **表达复盘对照**：跃迁档案表达条目新增 `gap_hits` / `gap_misses`——本场缺口词在回答文本里是否出现，复用 JD 对位同一套别名表与短 ASCII 词边界（`go` 不命中 `golang`）
- **报告回收缺口**：「本场设定」行追加 `缺口：A / B / C`，报告顶 / 历史行 / 会话顶三处共用同一格式化入口

### 修复
- 移动端筛选 chip 触控高度只有 28px：`ChipRow`（单选 / 多选）与 `PracticeFilters`（无命中建议）的可点击 button 漏加 `is-clickable`，r40 的 ≥44px 规则未生效（桌面 hover 反馈同时缺失），补 class 后复测 28 → 44px

### 运维与安全
- `.gitignore` 忽略 vitest 每次跑测试生成的 `frontend/vite.config.ts.timestamp-*` 临时文件

### 文档
- 新增五套交付文档：`docs/teamflow/20261116-r108-leap-archive/`、`20261116-r109-mobile-adaptation/`、`20261116-r110-jd-match/`、`20261116-r111-jd-interview-loop/`、`20261116-r112-report-focus-gaps/`（各自 PRD / TECHNICAL / ACCEPTANCE）
- `AGENTS.md` 追加 r108–r112 五条变更记录

### 验收
- 后端全量 1076 tests（仅 2 条本机 health 启动竞态，单独复跑 `test_health.py` 4 passed；CI Docker 环境全绿）；`ruff check` 通过
- 前端 45 个测试文件 582 tests / 0 failures；`typecheck`、`lint --max-warnings 0`、`build` 全过
- 生产：CI run `43900093846` 全绿（backend 285s / frontend 37s / Deploy 37s），`logs/deploy-state` = `206b389`，5 容器 healthy；公网 `/health` 200、`/docs` 404、TLSv1.3；`/api/jd-match` 与 `/api/leap-archive` 未登录均 401

## [v0.3.0] - 2026-11-16

运行时依赖降级兜底：PostgreSQL 仍是唯一权威主库，但挂了不再等于服务挂——SQLite 完整副本接管全部读写并在主库恢复后自动回切；Redis 挂了退化为进程内缓存。

### 新增
- **PG 故障兜底**：提交后逐笔镜像 SQLite 完整副本；主库不可达时副本接管读写，写操作与 `_offline_operations` 同事务落盘；恢复后暂停业务事务、按 `_offline_receipts` 幂等重放、重建副本再回切
- **Redis 故障兜底**：JSON 缓存退化为进程内 TTL + LRU（容量上限 `MEMORY_CACHE_MAX_ENTRIES`），限流退到进程内窗口、锁按单进程语义；删除屏障防止重连后旧值与旧会话复活
- **健康契约扩展**：`/health` 新增 `db_replica=ready|stale|na`，区分「主库在服务」与「还留着兜底」
- **唯一约束体检脚本** `scripts/audit_unique.py`：只读比对「`pg_index` 说唯一」与「数据实际有重复」

### 修复
- 恢复循环抢写锁：PG 不可达时每轮失败都把毫秒级副本写入挡到请求超时 → 恢复前先做不持锁的 PG 探活（实测 3945ms → 2ms）
- 副本损坏误伤健康主库 → 拆开「回放失败 fail-stop」与「副本重建失败」两类：后者只降级为 `db_replica=stale`，业务继续在 PG 上跑
- 副本接管期间 SQLite 自身报错冒 500 → 统一转可重试 503；`_open_sqlite()` 的 PRAGMA 失败补 `close()`，避免句柄锁死副本文件
- Redis 重连后旧值 / 已撤销会话复活 → tombstone + 前缀屏障 + 回放，待回放期间禁用探活捷径
- 停用账号未撤销既有会话 → `set_user_disabled()` 同时失效该用户全部会话
- 副本重建失败日志只有异常类型 → `ReplicaSyncError` 带 `table=` 与约束详情；重试从固定 2s 改为指数退避封顶 30s

### 运维与安全
- compose 新增 `skillcoach-sqlite` 持久卷与 `SQLITE_PATH`，副本进备份范围（PG 故障时它是唯一一份未回放写入）；后端写死 `--workers 1`，横向扩容前必须先拆协调器
- **生产事故处置**：上线后副本反复重建失败，定位为 `radar_techs_pkey` 在 `pg_index` 中 `indisvalid=true` 却不拦重复（索引缺条目，`ON CONFLICT` 判不出冲突），两次采集各插一份重复行；备份后去重 84→77 行、`REINDEX` 恢复约束力，副本随即 `ready`
- `cd_status.py` 在 run 进行中不再因 `conclusion` 为 `null` 崩溃

### 文档
- `docs/teamflow/20261112-r98-redis-pg/DEPLOY.md`：Redis 降级矩阵、副本备份判据、`db_replica` 排障表（含索引失配这一例）
- `ARCHITECTURE.md` §3.3.1：单一权威写库、两类恢复失败的语义边界、退避与日志可定位性
- `README.md`、`backend/.env.example` 同步新增配置项

### 验收
- 后端 1048 tests / 0 failed / 0 errors / 1 skipped；`ruff check backend/app backend/tests` 通过；前端 `npm run typecheck` 通过
- 隔离 project 实机闭环：在线写入毫秒级入副本 → 停 PG + Redis 后 `/health` 200 `db=sqlite`、读写正常 → 重启后端仍是副本且旧会话有效 → 起依赖后 `replayed=5` 自动回切、会话数一致
- 生产 `/health`：`db=postgresql`、`db_status=up`、`db_replica=ready`、`redis_status=up`

## [v0.2.0] - 2026-11-16

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
