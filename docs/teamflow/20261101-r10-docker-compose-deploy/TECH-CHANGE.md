# TECH-CHANGE · r10 容器化交付（Dockerfile + compose + nginx 反代 + 部署文档）

> 任务夹：`docs/teamflow/20261101-r10-docker-compose-deploy/` ｜ 分支 `feat/dev-skill-coach`（原地继续，Agent 不提交）
> 基线依赖：`docs/teamflow/20261031-r1-dev-skill-coach/`（端点契约）+ `docs/teamflow/20261101-r9-ai-provider-switch/`（AI 档位语义）
> 性质：**技术驱动返工** —— 零业务代码改动、零新依赖、不重写任何历史 PRD 的功能 AC。

## 1. 背景与目标
一句话：把「宿主机 `.venv` + `npm run dev`」的启动方式补齐为 `docker compose up -d --build` 一条命令的两容器交付（nginx 静态托管+反代 / FastAPI 非 root），并让「走 DeepSeek API」成为默认开箱可用的形态。

## 2. 影响面（改动白名单，白名单外一律不动）
- 新增：`backend/Dockerfile`、`backend/.dockerignore`、`frontend/Dockerfile`、`frontend/.dockerignore`、`frontend/nginx.conf`、`docker-compose.yml`、`.env.docker.example`、本夹 `DEPLOY.md`。
- 改动：`README.md`（**只加**「Docker 部署」一节，不动现有「快速开始」）、`.gitignore`（加一条白名单，见 3.6）、`docs/teamflow/memory.md`（回写约定）。
- 明确不动：`backend/app/**`、`frontend/src/**`、`backend/requirements.txt`、`frontend/package.json`、`.github/workflows/ci.yml`、`docs/teamflow/architecture/`、任何历史任务夹。

## 3. 技术方案要点

### 3.1 拓扑与判据
`浏览器 → frontend(nginx:80，宿主 ${WEB_PORT:-8080}) → /api、/health → backend:8000（仅容器内网）`
- 判据：`frontend/src/api/client.ts` 的 `BASE = VITE_API_BASE ?? ''` 是**相对路径**，生产必须同源反代；本轮**禁止**在前端硬编码后端地址、禁止设 `VITE_API_BASE`。
- `backend` **不发布 8000**：既避开宿主 8000（本地 uvicorn）与 5432（`ldt-postgres`）冲突，也只有 nginx 需要它；调试直连方式写进 DEPLOY.md（不默认开）。

### 3.2 backend 镜像
- `python:3.13-slim`（与宿主 3.13.9 一致；CI 仍 3.11 → 见 A-3）。
- 分层：`COPY requirements.txt` → `pip install --no-cache-dir -r requirements.txt` → `COPY app/ ./app/`。
- 非 root：`useradd -u 10001 -m app`；**`mkdir -p /data && chown app:app /data` 必须在 `USER app` 之前**——命名卷首次挂载继承镜像内目录所有权，非 root 才能写 SQLite（**不得** chmod 777、不得以 root 运行）。
- `ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DB_PATH=/data/app.db`。
- 启动：`uvicorn app.main:app --host 0.0.0.0 --port 8000`（compose 可覆写 command）；`HEALTHCHECK` 用 **python urllib** 打 `http://127.0.0.1:8000/health`（slim 无 curl，不装包）。
- `.dockerignore`：`.env`、`*.db`、`*.db-wal/-shm`、`tests/`、`__pycache__/`、`.venv/`、`*.log`、`pytest.ini`。

### 3.3 frontend 镜像（多阶段）
- stage1 `node:22-alpine`：`npm ci`（有 `package-lock.json`）→ `npm run build`（build 内含 typecheck）。
- stage2 `nginx:alpine`：`dist/` → `/usr/share/nginx/html`；自定义 `nginx.conf` → `/etc/nginx/conf.d/default.conf`。
- nginx 硬要求：SPA fallback `try_files $uri $uri/ /index.html`；`location /api/` 与 `/health` `proxy_pass http://backend:8000`（保留原 URI 前缀，勿改写）；`client_max_body_size 20m`（应用侧 `MAX_UPLOAD_MB=10` 仍为准）；gzip；`/assets/` 长效缓存（immutable）、`index.html` `no-cache`、`/api`+`/health` **`Cache-Control: no-store` 且不缓存**；`proxy_set_header X-Forwarded-*`。
- `.dockerignore`：`node_modules/`、**`node_modules-pnpm/`**（本机存在，不挡会给构建上下文塞入上千文件）、`dist/`、`.vite/`、`.npm-cache/`。

### 3.4 docker-compose.yml
- 服务 `backend`、`frontend`；均 `restart: unless-stopped`；`frontend` 依赖 `backend` 的 `condition: service_healthy`；`backend` 显式 `healthcheck`（python urllib，interval 30s / start_period 20s / retries 3）。
- `backend`：`env_file: [{path: ./backend/.env, required: false}]`（**引用，禁止把 Key 写进 compose**；`required:false` 保证新克隆缺 `.env` 时 `config/build/up` 不炸，`/health` 如实报未就绪）；`volumes: skillcoach-data:/data`；`environment: DB_PATH=/data/app.db`。
- `frontend`：`ports: ["${WEB_PORT:-8080}:80"]`。
- **不以 `environment` 覆盖 `AI_PROVIDER`**：compose 的 `${VAR}` 只读宿主/根 `.env`，写了就会把 `backend/.env` 里的显式选择冲掉（会踩 3.5 的坑）。

### 3.5 「默认走 DeepSeek」的落地方式（唯一处）
backend 的 compose `command` 里做确定性解析（`$$` 转义），**不进业务代码、不改 `config.py` 语义**：
```
AI_PROVIDER 非空 → 尊重用户选择
否则 AI_DEEPSEEK_API_KEY 非空 → export AI_PROVIDER=deepseek
否则 → 维持空＝legacy 三件套（AI_BASE_URL/AI_API_KEY 指 DeepSeek）
```
- 判据：legacy `.env`（现有宿主即此形态）照常 `ready=true`、`ai_provider=legacy`；新 `.env.docker.example` 用 `AI_DEEPSEEK_*` 则默认 `deepseek`。**任何路径都不允许「默认配置起不来」**。

### 3.6 零 Key 泄露与不提交
- 镜像内不得有 `backend/.env`、`*.db`（靠 `.dockerignore` + 白名单外不含 `.env` 的 COPY）。
- 门禁：`docker history` 与镜像内 `grep -r "sk-"` 均无命中；`git check-ignore -v backend/.env backend/app.db` 仍为忽略。
- **`.gitignore` 现为 `.env.*` + `!.env.example`**：`.env.docker.example` 会被一并忽略 → 必须追加 `!.env.docker.example`，否则示例文件进不了仓库（QA 必查）。

## 4. 行为兼容性影响（用户可见差异，逐条）
- 唯一新增可见面：`README.md` 多「Docker 部署」一节；部署后页面入口由 `:5173` 变 `:8080`（本机开发流程完全不变）。
- 用户可见功能/端点/错误 envelope/UI **零变化**；不新增、不替代任何功能 AC（本单取代：无）。
- 数据面：容器化后默认写卷内 `/data/app.db`，宿主 `backend/app.db` 不自动迁移（迁移只在 DEPLOY.md 给一条人工命令，禁止自动覆盖）。

## 5. 回归与验证计划
| # | 命令（根目录执行） | 期望 |
|---|---|---|
| V1 | `docker compose config` | 语法/变量解析通过，无未解析 `${}` |
| V2 | `docker compose build` | 两镜像构建成功 |
| V3 | `docker compose up -d` + `curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/` | `200`（前端页面） |
| V4 | `curl -sS http://127.0.0.1:8080/health` | `{"status":"ok",...,"ai_configured":true}` 且 `ai_provider` 为 `deepseek` 或 `legacy`(+DeepSeek 模型) |
| V5 | `curl -sS http://127.0.0.1:8080/api/courses` | `200` |
| V6 | 容器内真实链路（真实 Key，经 `env_file` 注入） | 上传简历 → `POST /api/resumes/{id}/profile` `200`、`skills` 有值、`source_quote` 逐字命中 → `POST /api/interviews` `200` |
| V7 | `docker compose down && docker compose up -d` 后重读画像/报告 | 数据仍在（卷生效） |
| V8 | `docker history --no-trunc <img>` / `docker run --rm --entrypoint sh <img> -c "grep -rl sk- /app \|\| echo CLEAN"` | 无 `sk-`；镜像内无 `.env`/`.db` |
| V9 | `git check-ignore -v backend/.env backend/app.db` + `git status --porcelain=v1 -uall` | 忽略生效；新增文件均为白名单内 |
| V10 | `cd backend && python -m pytest -q -p no:cacheprovider` | 全绿（地板 ≥305） |
| V11 | `cd frontend && npm run typecheck && npm run lint && npm test && npm run build` | typecheck 0 / lint 0 error ≤28 warn / vitest 109 / build 通过 |
| V12 | `curl -sS http://127.0.0.1:8080/health` 后 `docker compose logs --tail=50` | 日志无 Key、无栈 |

- **回归地板**：pytest ≥305、vitest 109、typecheck 0、lint 0 error（≤28 warning）、`npm run build` 通过、`/health` 200 —— 只增不减；本轮不改业务代码，故地板数值不变。
- 环境事实：Agent 侧 Docker **实测可用**（29.9.2 / Compose v5.6.1，`docker ps` 正常）；若 QA 机不可用，必须如实写「未能实跑」并交出上表命令清单，禁止伪造构建/运行成功。

## 6. 风险与回滚
- **R-1 3.13 wheel 缺失**（`httptools`/`uvloop`/`watchfiles` 会退化为源码编译，slim 无 gcc 即失败）→ 本机 3.13.9 已跑通全部依赖为强证据；失败则 `FROM python:3.11-slim`（与 CI 对齐，一行）。
- **R-2 非 root 写卷 EACCES** → 见 3.2 的 chown 时序；退路为 compose `user:` 映射宿主 UID（不采用 777）。
- **R-3 端口冲突** → 默认 8080、backend 不发布；被占时改 `WEB_PORT`。
- **R-4 `env_file.required:false` 语法** → compose v5.6.1 支持；旧版报错时删 `required` 并先 `copy backend\.env.example backend\.env`。
- **R-5 镜像含 pytest/ruff**（+约 30MB）→ 本轮不拆 `requirements-prod.txt`（会动 CI 缓存键与依赖清单）。
- **回滚**：删除新增 8 个文件 + 还原 `README.md`/`.gitignore` 两处改动；数据零迁移（`docker volume rm <项目>_skillcoach-data` 即回到宿主 `backend/app.db`）。

## 7. 任务拆分（按文件边界，禁止交叉改动）
- T1 backend 镜像：`backend/Dockerfile`、`backend/.dockerignore`。
- T2 frontend 镜像：`frontend/Dockerfile`、`frontend/.dockerignore`、`frontend/nginx.conf`。
- T3 编排与配置：`docker-compose.yml`（含 3.5 的 command 解析）、`.env.docker.example`、`.gitignore` 白名单。
- T4 文档：本夹 `DEPLOY.md`（最短路径/健康检查/日志/lmstudio 的 `host.docker.internal:1234` + 注释掉的 `extra_hosts`/备份恢复/故障排查）、`README.md` 的 Docker 小节（三步）。
- T5 联调实跑：V1–V9（含真实链路与重建保数据）。
- T6 收尾：V10–V12 门禁复跑 + `memory.md` 回写（由技术阶段先行完成，dev 不重复改）。

## 8. 假设与待澄清（选择权在用户，先按此落地）
- **A-1 默认 DeepSeek 的落地形态**：选 compose `command` 内推导（legacy 不破）。若要求 compose 显式钉 `AI_PROVIDER=deepseek`，则现有 legacy `.env` 会直接「未就绪」，必须同步把 `.env` 迁到 `AI_DEEPSEEK_*`（或先在 compose 里做同一段回落逻辑）。
- **A-2 端口暴露**：只发布 `${WEB_PORT:-8080}`、不发布 8000。若要宿主直连后端（Postman 调试），加 `ports: ["8000:8000"]`（会与本地 uvicorn 抢端口）。
- **A-3 基础镜像版本**：3.13-slim vs CI 3.11 双版本并存。若要求单一版本，改 `FROM` 或在 `ci.yml` 升 3.11→3.13（后者超出本轮白名单，需另开）。
- **A-4 示例 env 的位置**：`.env.docker.example` 放仓库根（compose 变量插值只认根 `.env`），与 `backend/.env.example` 并存。若要求单一样例文件，需并入 `backend/.env.example` 并同步 `.gitignore`。
- **A-5 传输层**：本轮只 HTTP（本机/内网）。公网需另加 TLS（前置反代或 certbot），不在本轮。
- **A-6 上传上限双层**：nginx 20m / 应用 10m，以应用侧为准；若要放宽，两处同改并同步 docs。
