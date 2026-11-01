# ACCEPTANCE · r10 容器化交付（docker compose 两容器 + nginx 同源反代 + 部署文档）

> **验收结论：✅ 通过**（0 条 P0/P1/P2；2 条 P3 文档级遗留，其中 1 条验收期已就地订正）。
> 验收对象：本夹 `TECH-CHANGE.md` 的 V1–V12 验证计划 + 注入的架构蓝图。本夹无独立 PRD.md —— 本轮是**技术驱动返工**（零业务代码改动、不新增/不替代功能 AC，技术单 §4 明确「取代：无」），故逐项核对以 V1–V12 + 蓝图为契约。
> 基线依赖：`20261031-r1-dev-skill-coach`（端点契约）+ `20261101-r9-ai-provider-switch`（AI 档位语义），回归地板只增不减。

## 1. 验收方式

**不以「文件存在 / QA 转述」判绿**：验收期内我在本机独立复跑了构建产物、运行态、真实 AI 链路与两道门禁（Docker 29.9.2 / Compose v5.6.1 可用，栈已在运行），并在 QA 的 6 个自查脚本上重跑 3 个（derive / interface / surface）做交叉验证。

## 2. 逐项验收表（V1–V12）

| # | 验收项 | 我的核对方式 | 结果 |
|---|---|---|---|
| V1 | `docker compose config` 可解析 | `docker compose ps` + QA `check_t3` 契约脚本（含 `config` 解析） | ✅ |
| V2 | 两镜像构建成功 | 两镜像在运行（`code_learning-backend` / `-frontend`，compose build 产物），frontend 为多阶段产物 | ✅ |
| V3 | 宿主入口 `:8080` 页面 200 | `curl -o /dev/null -w %{http_code}` → **200** | ✅ |
| V4 | `/health` 就绪且供应商口径正确 | `{"status":"ok","ai_configured":true,"ai_provider":"legacy","ai_model":"deepseek-chat"}`（legacy＝DeepSeek 直连，符合蓝图「默认走 DeepSeek」判定优先级） | ✅ |
| V5 | `/api/courses` 200 | 经 nginx 反代 → **200** | ✅ |
| V6 | 真实 Key 全链路（上传→画像→面试） | **我亲自跑**：`POST /api/resumes` 200（431 字）→ `POST /api/resumes/{id}/profile` **200 / 2.87s**，`skills` 13 条、`projects` 8 条、`target_role=高级后端开发工程师`，证据项带 `resume_id`+`file_name` 溯源；QA 另记录面试 `total=9`、12 轮作答至 completed、报告 `shortfalls=3` | ✅ |
| V7 | `down`/`up` 后数据仍在（卷生效） | 卷 `code_learning_skillcoach-data` 内 `app.db` 274,432B、属主 `app:app`；`documents=5 / profiles=1 / reports=4 / questions=80`、`pragma integrity_check=ok` —— 数据存活于多次 QA 重启之后 | ✅ |
| V8 | 零 Key 泄露 / 镜像内无 `.env`、`.db` | `docker history --no-trunc` 两镜像 grep `sk-` 均 **0**；backend 镜像 `/app` 仅 `app/`+`requirements.txt`，无 `.env*`/`*.db*`；frontend 镜像 `command -v node` → **NO_NODE**（无源码/node） | ✅ |
| V9 | `.gitignore` 生效 + 改动面在白名单内 | `git check-ignore`：`backend/.env`→`.gitignore:41`、`backend/app.db`→`:29` 命中；`docker.env.example`、`docker-compose.yml` 未被忽略（`.gitignore` 零改动成立）。`git status` 仅 8 新增 + `README.md`/`memory.md` 改动 22 行，`backend/app/**`、`frontend/src/**` **0 改动** | ✅ |
| V10 | pytest 全绿（地板 ≥305） | 本机全程重跑 → junit 实测 **349 收集 / 348 passed / 1 skipped / 0 failed**（地板 305） | ✅ |
| V11 | 前端四道门禁 | typecheck **0 error**；lint **0 error / 28 warning**（≤28）；vitest **109 passed**（8 文件）；build **OK**（dist 267.81 kB） | ✅ |
| V12 | 日志无 Key / 无栈 | `docker compose logs --tail=200` grep `sk-…`/`Traceback` → **0** | ✅ |

**运行态反代关键配置（`nginx -T` 生效配置，非源文件）**：`client_max_body_size 20m`、`gzip on`、`try_files $uri $uri/ /index.html`、`/assets/` `public, immutable`、`/api/` 与 `= /health` 各含 `proxy_pass http://backend:8000` + `proxy_read_timeout/send 1300s` + `Cache-Control: no-store` —— 与仓库 `frontend/nginx.conf` 一致。

## 3. 架构一致性核对（强制项）

| 蓝图要求 | 核对 | 结果 |
|---|---|---|
| 不新增业务模块，`backend/app/**`、`frontend/src/**` 零改动 | `git status` 全量改动面 | ✅ 符合 |
| backend：分层 requirements→pip→`COPY app/`；非 root `app:10001`；`chown /data` 早于 `USER app`；urllib 探针；`EXPOSE 8000` | Dockerfile 逐行 + 运行态 `uid=10001(app)`、`/data` 属主 `app:app` | ✅ 符合 |
| frontend：多阶段（node 构建 → nginx 运行），最终镜像无 node/源码 | 镜像内 `command -v node` 无命中，`html` 仅 `index.html/assets/50x.html` | ✅ 符合 |
| nginx：SPA fallback / 同源反代不改 URI 前缀 / 1300s / 20m / no-store / 缓存分层 / gzip | 运行态 `nginx -T` 逐条比对 | ✅ 符合 |
| compose：`env_file` 引用 + `required:false`；`environment` 仅 `DB_PATH`；backend 不发布端口；`service_healthy` 门控；卷 `skillcoach-data` | `docker-compose.yml` 全文 + `ps`（backend `8000/tcp` 无宿主映射，frontend `0.0.0.0:8080->80`，backend `(healthy)` 后前端起） | ✅ 符合 |
| 示例文件定名 `docker.env.example`；`.gitignore` 零改动 | `git check-ignore .env.docker.example` → 命中 `.env.*`（证实旧名不可用），当前示例未被忽略 | ✅ 符合 |
| 贯穿契约（服务名/8000/卷名/8080）单源写入 `memory.md` | memory.md 第 22 行「容器化交付约定」+ 三处文件对账（QA interface 20/20） | ✅ 符合 |

**重复实现 / 适配漂移复核**：健康探针两份（`Dockerfile` HEALTHCHECK 与 compose healthcheck）payload 逐字相同、仅 interval/start_period/retries 不同；代理路由表两份（vite `:5173` / nginx `:80`）前缀集合一致；端口 8000 在 6 处一致；「默认供应商」判定只落 compose `command`（业务侧仍由 `config.resolve_ai` 单一出口）且优先级已写入 `memory.md` —— **无重复实现漂移、无应抽未抽的抽象、无既有结构破坏**。

**交叉复跑 QA 自查脚本（我重跑，非 QA 转述）**：`check_qa_r10_derive.py` → ALL PASSED（含「environment 未覆盖 AI_PROVIDER/*_API_KEY」静态禁令）；`check_qa_r10_interface.py` → **20/20**；`check_qa_r10_surface.py` → **33/33**。

## 4. 遗留（全部 P3，不阻塞验收）

| 编号 | 内容 | 处置 |
|---|---|---|
| P3-1 | `memory.md` 第 22 行仍写「`.gitignore` 需追加 `!.env.docker.example`」，指向刻意不创建的旧名 | **验收期就地订正**：改为「示例定名 `docker.env.example`；`.gitignore:42` 的 `.env.*` 会命中旧名且该名在文件工具侧撞凭据围栏，故禁用；`.gitignore` 零改动」。已 grep 复核（`env.docker.example` 仅剩订正后的说明性提及） |
| P3-2 | `DEPLOY.md` 未给「临时直连后端调试」配方（技术单 §3.1 要求写进文档、不默认开） | 非阻塞，给出可照抄命令：`docker compose run --rm -p 8000:8000 backend`（临时容器，不改 compose 默认不发布端口）→ `curl 127.0.0.1:8000/health`。建议 dev 侧下一轮补一小节（本夹文档属 dev 产物，验收不代改） |
| 已知取舍 | 运行镜像含 `pytest`/`ruff`（约 +30MB），因 `requirements.txt` 未拆 | 技术单 R-5 已显式接受（拆分会动 CI 缓存键与依赖清单，超白名单），记为**取舍非缺陷** |

## 5. 人工补测清单（环境限制，非交付缺陷；沿用 QA §5）

8080 页面视觉与四步点选（沙箱无法起浏览器截图）｜真实 LM Studio 档下 1300s 长请求（本机 >60s 单次画像不应 504）｜Linux/WSL 下 `host.docker.internal`（需 `extra_hosts`，DEPLOY §4 有注释示例）｜备份→恢复全流程含 `chown` 节点。

## 6. 结论

交付以 `docker compose up -d --build` 一条命令起两容器：nginx 同源反代承载全部前端流量与 `/api`、`/health`，backend 非 root 只在内网、SQLite 落命名卷且重建保数据；真实 Key 全链路经浏览器入口跑通（验收期我亲自复跑画像 200/2.87s）；零 Key 进入镜像与日志；门禁只增不减（pytest 348、vitest 109、typecheck 0、lint 0 error）；实现与架构蓝图逐条相符，无重复实现漂移。2 条 P3 均为文档口径，其中 1 条已就地订正。

验收结论：✅ 通过
