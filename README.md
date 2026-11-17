# 逃跑计划 · 外包工程师的跃迁工作台

[![CI](https://github.com/miaogan/code_learning/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/miaogan/code_learning/actions/workflows/ci.yml?query=branch%3Amaster)

**从外包交付到更高平台，不靠一句“我想进大厂”，靠可验证的能力证据。**
当前主线是 **AI 应用 / Agent 后端**：盘点简历与项目证据，用模拟面试和 ACP／工程题验证能力，把短板转为学习、项目补强和表达动作。

现有闭环：**上传简历 → 可溯源技术画像 → 模拟面试 / 笔试 → 带证据的短板报告 → 教程与练习补强**。
v0.4.0 起再接一段岗位闭环：**粘贴 JD → 技术词三态与缺口 → 带缺口定向召对 → 报告回收缺口 → 跃迁档案汇总**。
技术选型与代价见 [设计取舍](#设计取舍为什么这么做)。

- 画像的每条技能与项目都带 `sourceQuote`（简历原文），可溯源、可编辑。
- 每道题有得分，每条短板能指回具体题目（如 `Q3 · 4/10`）。
- 每条短板直接挂 1–3 门基础课程，点开即学。
- 站内教程覆盖题库全部 8 个方向（前端 / 后端 / SQL 与数据库 / 中间件与运维 / 算法与数据结构 / 计算机基础 / AI 工程 / 研发工程实践），每章标「基础 / 进阶 / 高级」，读完可直接跳到该章二级方向的专项练习（该二级方向题目不足时自动补充同方向题目）。
- 阅读进度按小节记录（本地、按账号隔离）：目录页有「继续学习」入口与每章进度，点进去直接落在上次读到的那一节。
- 文章页带章内目录：宽屏常驻右栏、窄屏折叠；当前小节随滚动高亮，读过的节打 ✓，点击即跳到该节锚点。

> **当前版本**：**0.4.0**（2026-11-17 发版，tag `v0.4.0`）。r1 起打底的四步闭环：上传解析 → 画像（每条带 `sourceQuote`、可逐条编辑）→ 模拟面试逐题评分 / 笔试题智判分 → 短板报告（证据可溯源 + 课程直链）→ 历史对比与 `.md` 导出。
>
> v0.4.0 在其上补的是**岗位闭环**：`/jd` 岗位对位（`POST /api/jd-match`）、`focus_gaps` 缺口驱动定向追问、报告「本场设定」回收缺口、`/leap` 跃迁档案（`GET /api/leap-archive`）。三处都是 **零 AI 新增、零新表、零分数**——不产出匹配分或百分比，只给可回溯的证据。
>
> 版本记录见 [CHANGELOG](./CHANGELOG.md)，端点契约见 [ARCHITECTURE](./docs/teamflow/architecture/ARCHITECTURE.md)，发版与回滚规则见 [RELEASE](./docs/teamflow/20261114-cicd/RELEASE.md)。
>
> 错误统一为中文 envelope（`{ "error": { code, message, retryable } }`），前端据此给出中文提示，不会白屏或 500。

## 跃迁路线（r56 起）

| 阶段 | 已有能力 | 能回答的问题 |
| --- | --- | --- |
| 盘点现状 | 简历解析、逐条原文溯源、项目证据累积 | 我有哪些真实经历，哪些结论有依据？ |
| 验证能力 | 多轮面试、**缺口驱动定向追问**、1300+ 道题库、ACP 应用工程题、成绩趋势 | 我是“见过名词”，还是能解释、能选型、能排障？ |
| 形成证据 | **JD 岗位对位**（技术词三态 + JD 原句 + 画像证据 + 缺口二分）、诊断报告、简历要点、离线评测与可靠性工程实践 | 这份 JD 要什么、我有哪些可回溯的证据、差在哪？ |
| 持续补强 | 40 章教程、专项练习、7 天学习计划 | 下一项最值得投入的行动是什么？ |
| 汇总展示 | **跃迁档案**：目标岗位差距 + 项目工程证据 + 面试表达，一页三块且同源 | 我的证据链现在长什么样？ |

**v0.4.0 已把这三者汇成「跃迁档案」**（`/leap`），并把缺口接进出题与复盘。下一步候选是表达交付的语音分析与投递流程管理；**不做面试中的实时 copilot**——实时喂答案与「真实能力、不虚构跃迁」的定位冲突。ACP 是知识补充，不等同于工作能力或录用保证；没有把模拟评测、未接真实模型的 dry-run 或刷题量包装成生产经验。
路线与边界见 [r56 产品方案](./docs/teamflow/20261110-r56-escape-plan-rebrand/PRD.md)。

## 快速开始（三步）

```bash
# 0) 首次启动依赖：PostgreSQL + Redis（已有完整 SQLite 副本时，后续 PG/Redis 故障可降级）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
#    PG → 127.0.0.1:5433，Redis → 127.0.0.1:6380（与 backend/.env.example 一致）

# 1) 后端
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip
copy .env.example .env                              # macOS/Linux: cp .env.example .env
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
# 探活：curl http://127.0.0.1:8000/health  →  {"status":"ok",...}

# 1.5) 建号（r23：不开放注册，账号由管理员创建，返回一次性初始密码）
.venv/Scripts/python -m app.admin_cli create-user --email me@example.com --name 我 --mode own
#   其他管理命令：set-mode（own/shared）、disable（--undo 启用）、reset-password（旧会话立即失效）、list
#   存量数据（r23 之前的数据都在 user_id='default'）：建号时加 --id default 直接接管，
#   或对已有账号执行 adopt-default --email me@example.com 把旧数据改挂过去

# 2) 前端（另开终端）
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173，/api 与 /health 已代理到 :8000
```

`.env` 里填 `AI_API_KEY` 后 AI 链路才有真实输出；**不填也不会 500**，页面会给出中文提示（AC-8）。

## Docker 部署（可选，一条命令起五容器：backend / frontend / postgres / redis / embedder）

不装 Python / Node 也能跑：`frontend`（nginx 托管构建产物 + 同源反代 `/api`、`/health`）+ `backend`（FastAPI，非 root、单 worker、只在容器内网）+ `postgres`（在线权威主库）+ `redis`（限流窗口 / 会话缓存 / 读缓存 / 分布式锁的共享层）。PG 正常时逐笔维护 SQLite 完整副本；PG 故障时副本接管读写，恢复后重放离线变更。Redis 故障使用带 TTL / LRU 的内存缓存。PG 与 Redis **不发布宿主端口**，公网入口只有 nginx。

```bash
# 1) 准备配置：backend/.env 是容器唯一的配置来源，需在其中填上真实 AI_DEEPSEEK_API_KEY
#    首次部署（还没有 backend/.env）：照 docker.env.example 建一份再填 Key
copy docker.env.example backend\.env               # macOS/Linux: cp docker.env.example backend/.env
#    已有 backend/.env：只手工补 AI_DEEPSEEK_API_KEY / AI_PROVIDER 两个键，**别覆盖原文件**

# 2) 构建并启动
docker compose up -d --build

# 3) 打开 http://127.0.0.1:8080（先看 /health：ai_configured=true 表示 AI 链路可用）
docker compose ps        # backend 的 STATUS 应带 (healthy)
```

- **换端口**：把 `docker.env.example` 复制成仓库根 `.env`，改 `WEB_PORT=127.0.0.1:8099`（格式是 `[绑定地址:]端口`，**不要只写端口号**，那会绑 `0.0.0.0`），再 `docker compose up -d`。默认 `127.0.0.1:8080` 只绑回环。
- **从 SQLite 升级**（r97 → r98）：停机 → 备份 `app.db` → 起 PG 建表 → `scripts/migrate_sqlite_to_pg.py` 迁移（幂等可重跑，带行数校验与序列复位），命令见 [r98 迁移手册](./docs/teamflow/20261112-r98-redis-pg/DEPLOY.md)。
- **数据库镜像**（r100）：PG 服务用 `pgvector/pgvector:pg16`（PostgreSQL 16 基线不变）——RAG 向量检索的 `vector` 扩展与 ivfflat 余弦索引在库内完成；无扩展的环境（如官方 postgres:16-alpine）应用层自动降级为「取回后 Python 余弦」，`engine` 字段如实报告。
- **降级边界**：后端固定单进程、单 worker，禁止仅增加 `--workers` 或副本来扩容。SQLite 完整副本与离线日志在 `skillcoach-sqlite:/data`，不是临时缓存；有未回同步变更时删除会丢数据。首次没有完整副本时 PG 不可用仍返回可重试 503。
- **备份**：`./scripts/backup_db.sh`（`pg_dump -Fc` + `pg_restore -l` 自检 + 滚动保留），建议进 cron；同时备份 `skillcoach-sqlite` 卷，具体一致性步骤见部署手册。
- **建号（r23）**：`docker compose exec backend python -m app.admin_cli create-user --email me@example.com --mode own`（容器内执行，数据落在同名卷）。
- **停止**：`docker compose down`（**保留**数据卷）；`docker compose down -v` 会连数据一起删。
- **排障与运维**（lmstudio 本地档、备份恢复、502 / 413 / 504 排查）：见 [DEPLOY.md](./docs/teamflow/20261101-r10-docker-compose-deploy/DEPLOY.md)。
- **公网部署（r97）**：内网这套只监听 http，**不能直接对外**。上公网用生产覆盖层（TLS + 安全响应头 + 启动期安全校验）：
  ```bash
  cp backend/.env.production.example backend/.env   # 改 CORS_ORIGINS / SECRET_KEY / AI Key
  cp deploy.env.example deploy.env                  # 改 PUBLIC_DOMAIN / ACME_EMAIL
  ./scripts/cert.sh init                            # 先签证书（80 需空闲）
  docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env up -d --build
  ./scripts/backup_db.sh                            # 备份（建议进 cron）
  ```
  完整顺序、验收命令、排障表、安全清单见 [公网部署手册](./docs/teamflow/20261112-r97-public-deploy/DEPLOY.md)。

## 自检命令

| 位置 | 命令 | 期望 |
| --- | --- | --- |
| `backend/` | `python -m pytest -q` | 全部通过（AI 全链路注入 `FakeAI`，**零网络**）。**前置**：需要可用的 PostgreSQL（默认 `127.0.0.1:5433`），先 `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis` |
| `backend/` | `python -m ruff check app tests` | All checks passed |
| `frontend/` | `npm run typecheck && npm run lint && npm test && npm run build` | 无错误，生成 `frontend/dist/` |
| `backend/` | `pip-audit -r requirements.txt` | `No known vulnerabilities found` |
| `frontend/` | `npm audit --omit=dev --audit-level=high` | 无 high / critical（当前 2 条 moderate 属 `react-router`，见下方 CI 说明） |
| 根 | `curl -sS http://127.0.0.1:8000/health` | `{"status":"ok",...}` |
| 根 | `grep -riE "sk-\|api_key\|AI_API_KEY" frontend/src frontend/dist \|\| echo NO_KEY_LEAK` | `NO_KEY_LEAK`（AC-8） |

CI 双 job 跑在 [GitHub Actions](https://github.com/miaogan/code_learning/actions)。工作流覆盖类型检查 / lint / 测试 / 构建、题库字节门禁、5 个离线评测门禁，以及前后端依赖漏洞审计（`pip-audit` 对 `requirements.txt`，`npm audit --omit=dev` 只扫进构建产物的生产依赖，阈值 high）。r98 起 backend job **自带 `postgres:16-alpine` + `redis:8-alpine` 服务容器**（healthcheck 通过才开跑）——SQLite 下线后测试与检索评测都连真库，CI 不再有「没有数据库的测试」这种假绿。依赖版本漂移由 [Dependabot](./.github/dependabot.yml) 每周提 PR（pip / npm / github-actions 三路）。已知未修的 2 条 moderate 属 `react-router` 6.x（`GHSA-wrjc-x8rr-h8h6` 开放重定向），修复要求升到 7.x（破坏性路由 API 变更），故留在升级批次里单独验证。

评测与检索证据（零网络、可复跑）：

```bash
python -X utf8 scripts/eval_harness.py --check              # 30 例金标集回归门禁（只读，不写 REPORT.md）
node scripts/eval_retrieval.mjs --check                     # 教程侧 BM25 召回门禁（只读）
python -X utf8 scripts/eval_question_retrieval.py --check   # 题目侧 PG 检索召回门禁（只读，需 PG）
python -X utf8 scripts/eval_rag.py --check                 # RAG 三态检索门禁（关键词/语义/RRF 融合，只读，需 PG）
python -X utf8 scripts/eval_rag_judge.py --check           # RAG 生成评审 DRY-RUN 门禁（LLM-as-judge 管线，只读，需 PG）
# 真模型对比（不进 CI，需 AI_LIVE=1 与 AI_EMBED_BASE_URL/AI_EMBED_MODEL，产出 RAG-LIVE-REPORT.md）
AI_LIVE=1 python -X utf8 scripts/eval_rag.py --live
python -X utf8 scripts/eval_reliability.py                  # 故障注入 → RELIABILITY-REPORT.md
python -X utf8 scripts/benchmark.py                         # 并发写锁 / 导入 / 检索 → PERF-REPORT.md（r98 前口径，见下）
python -X utf8 scripts/seed_eval_demo.py --dry-run          # /eval 看板合成演示数据（不写库）
python -X utf8 scripts/eval_live.py --check                 # 在线评测脚手架 dry-run 门禁（零网络 / 零 Key）
```

> 带 `--check` 的是只读 CI 门禁（**不写任何文件**），不带的是会重写对应报告的生成命令；`benchmark.py` 依赖本机磁盘与 CPU，**刻意不进 CI**（跨机器分位不稳定会导致 flaky），且它压的是**临时 SQLite 库**——r98 换 PG 后这条写锁路径已不存在，数字只能与历史版本纵向比对，不代表当前数据层性能，待改写为 PG 基准。所有指标来自合成数据 / 同源标注 / 模拟故障，只用于回归检测与实现可用性证明，不代表模型能力或生产 QPS；口径与限制见 `docs/teamflow/20261109-r51-resume-highlight-engineering/TECHNICAL.md §6–§8`。
>
> **在线质量评测轨道**：`scripts/eval_live.py` 默认 dry-run，只有 `--check` 进 CI。真跑需
> `AI_LIVE=1 python -X utf8 scripts/eval_live.py --live`（消耗第三方配额、不进 CI），
> 产出 `docs/eval/traces/` 脱敏轨迹与 `docs/eval/LIVE-REPORT.md`。版本锁定 prompt/model/rubric，
> 轨迹只存元数据与 sha256，绝不写简历正文 / Key / 提示词全文。**当前报告标注 DRY-RUN、真实模型未实跑**，
> 不能当成模型质量指标写进简历。

## 分支、交付与回滚

- **分支模型**：`master` 是受保护的发布存档主干（只接收已验收的版本批次，不部署），`dev` 是日常开发与**唯一自动部署**分支（push 到 `dev` 经 CI 双门禁后自动部署生产）。生产实际运行 `dev` 的 HEAD。历史需求改动曾从基线 `32487b4` 起在 `feat/dev-skill-coach` 上完成，该分支已删除。
- **版本发布**：`master` 不直接开发、不直接合入；每个版本批次走 `vX.Y.Z` tag → `release/vX.Y.Z` 临时分支 → PR → `master`（合并后删临时分支，稳态只留两条分支）。版本号规则、准入清单与操作步骤见 [`docs/teamflow/20261114-cicd/RELEASE.md`](docs/teamflow/20261114-cicd/RELEASE.md)，版本内容见 [`CHANGELOG.md`](CHANGELOG.md)。
- **提交**：由 Agent 执行，按语义分批——每轮改动（代码 + `docs/teamflow/` 任务夹 + `AGENTS.md` 变更记录）合成**一个语义完整的 commit**，不留「只为跑通而存」的中间提交；提交前先过门禁（`pytest` / `ruff` / `typecheck` / `lint` / `build`），推送 `dev` 后由 CI 双门禁把关并自动部署生产。跨需求交织在同一批文件时（如契约与样式表），允许合并为一个 commit，但提交信息正文要分段写清各自范围。
- **发版即合并**：`master` 只经 `release/vX.Y.Z` 分支的 PR 合入（merge commit，不用 squash / rebase），合并后删临时分支。单人仓库的 approval 无法自我满足，按 [`RELEASE.md` §5.1](docs/teamflow/20261114-cicd/RELEASE.md) 的标准动作处理：**先等三项必需检查全绿**，再只把 `required_approving_review_count` 调 0，合并后 `finally` 立即恢复 `1` 并逐字段复验；长期方案是加第二个协作者或交给 CI 自动合并。
- **回滚到基线（改动整体可撤销）**：

```bash
git reset --hard 32487b4 && git clean -fdx
```

  > `-fdx` 会连被忽略的 `node_modules/`、`frontend/dist/`、`.venv/`、本地 `*.db` 一起清掉；只想丢弃手改的代码、保留依赖时用 `git stash -u` 或 `git clean -fd`（保留 `-x` 的忽略项）。

### 不提交清单（`.gitignore` 已覆盖）

`node_modules/`、`dist/`、`frontend/.vite/`、`*.tsbuildinfo`、`__pycache__/`、`*.py[cod]`、`.venv/`（含 `backend/.venv/`）、`*.db` / `*.sqlite3`、`.env` 与 `.env.*`（**`backend/.env.example` 例外，必须提交**）、编辑器与系统目录，以及 TeamFlow 运行日志 `logs/teamflow/`（run 结束由 host 归档到 `$DSH_HOME`，不进仓库）。

## 目录

```
frontend/   React 18 + Vite 5 + TypeScript（5 步向导 + 学习 / 练习 / 卷宗 / 跃迁 / 对岗等工具页 + 设计 token）
backend/    FastAPI + PostgreSQL + Redis（app/routers、app/services、app/seed）
docs/teamflow/   架构总览、产品记忆、每需求一个任务夹
```

## 安全边界（AC-8 / r23）

- 模型 Key 只出现在 `backend/.env`（内置 Key）；用户自带 Key 以 Fernet 密文存库，接口只回显后 4 位。
- 上传的简历**不落原文件**，只存抽取后的正文；错误响应不含路径、堆栈与模型端点。
- r23 起登录后才能使用：服务端会话 + HttpOnly Cookie（`sc_session`），所有业务表按 `user_id` 隔离，
  跨用户按 id 取数一律 404；不开放注册，账号由管理员用 `app.admin_cli` 创建。

## 设计取舍（为什么这么做）

> 这里只记**放弃的方案与付出的代价**；完整论证见 [ARCHITECTURE §1.1](./docs/teamflow/architecture/ARCHITECTURE.md)。

| 取舍 | 放弃了什么 | 代价与兜底 |
|---|---|---|
| 不做 SSR / Next.js | SSR、文件路由、RSC | 首屏无 HTML 直出、路由表手写；首屏只等本地 `/health`，可接受 |
| 后端选 Python 而非 Node | 单运行时（全 TS）的部署便利 | 两套工具链；用三步启动、`docker compose` 与 CI 双 job 兜住 |
| PostgreSQL 主库 + SQLite 完整副本，直连 SQL、不用 ORM / 迁移框架 | SQLModel、Alembic | 手写 SQL 与双库方言适配，改字段要同时维护幂等补列和副本结构；结构化产物以 JSON 文本列存，DDL 只在 `core/db.py`、SQL 只在 `core/repository.py`。PG 在线时是唯一权威写库，故障时完整副本接管并记录离线日志，恢复后重放；本地副本和内存缓存要求单 worker |
| 手写 CSS + token，不引 UI 库 / Tailwind | 原子类的书写效率 | 类名集中维护；新增组件必须复用 `tokens.css`，禁止裸色值与裸尺寸，改尺寸要回写 DESIGN §0.7 推导 |

**能力边界（避免误读）**：本项目是「LLM 应用工程化与可靠性」实践 —— AI 侧是 OpenAI 兼容调用 +
pydantic 结构化校验，外加 r100 起的 **RAG 检索管线**（分块 → embedding → pgvector 余弦索引 →
向量 / 关键词 RRF 融合 → 带引用白名单的生成）与 **RAG 自动评审**（检索三态评测门禁 +
LLM-as-judge 忠实度 / 相关性评分）；**没有**多 Agent 编排（太傅是单 Agent + ≤3 轮工具循环）
或模型训练。题库 / 教程 / 学习计划属于规则与内容工程，不是 RAG 语料之外的第二套检索系统。
评测体系、检索增强与引用归因的实施方案见 [r51 技术方案](./docs/teamflow/20261109-r51-resume-highlight-engineering/TECHNICAL.md)
与 [r100 技术方案](./docs/teamflow/20261115-r100-rag-evidence/TECHNICAL.md)。

## 验收速览

闭环是否成立，按 PRD 的 AC-1 ~ AC-10 逐条走：上传 → 画像 → 面试/笔试 → 报告 → 课程。每条 AC 的验收证据、端点判分口径与错误码见任务夹 [TECHNICAL §2](./docs/teamflow/20261031-r1-dev-skill-coach/TECHNICAL.md) 与 `ACCEPTANCE.md`；后端测试全部注入 `FakeAI`，不依赖真实模型与外网即可复跑。

每次发版另按 [RELEASE §3.3](./docs/teamflow/20261114-cicd/RELEASE.md) 跑公网 `verify_public.py` 的 44 项（最近一次 v0.4.0：`demo@skillcoach.local` 与 own-key 账号 `ac@miao.com` **各 44/44**，另有新端点专项 23/23 与跨账号隔离实测）。

## 许可证

本项目代码与文档以 **MIT** 发布，全文见 [LICENSE](./LICENSE)。

- **第三方题库素材**：`backend/app/seed/questions.json` 中 `source = "fe-interview"` 的 20 道题改写自 [haizlin/fe-interview](https://github.com/haizlin/fe-interview)（MIT），上游链接、改写说明与许可全文见 [NOTICE-fe-interview.md](./docs/question-bank-staging/NOTICE-fe-interview.md)；其余素材为自建，来源留痕见 [PROVENANCE.md](./docs/question-bank-staging/PROVENANCE.md)。
- **依赖许可**：后端依赖闭包内仅 `certifi` 为 MPL-2.0（文件级弱 copyleft，未修改其源码即不产生源码开放义务），其余为 MIT / BSD / Apache-2.0 / PSF；前端生产依赖闭包全部 MIT。**没有** GPL / AGPL / SSPL / EUPL 依赖，也无 vendored 第三方源码、字体或图标打包。
- **镜像与系统包**：容器基础镜像（`python:3.13-slim` / `nginx:alpine`）自带系统包按各自许可证随镜像分发，本项目未修改这些包。
