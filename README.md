# Skill Coach · 开发者能力提升教练

把「我不知道该补什么」变成一条可验证的闭环：**上传简历 → 技术画像 → 模拟面试 / 笔试 → 带证据的短板报告 → 精选基础课程**。

- 画像的每条技能与项目都带 `sourceQuote`（简历原文），可溯源、可编辑。
- 每道题有得分，每条短板能指回具体题目（如 `Q3 · 4/10`）。
- 每条短板直接挂 1–3 门基础课程，点开即学。
- 站内教程覆盖题库全部 8 个方向（前端 / 后端 / SQL 与数据库 / 中间件与运维 / 算法与数据结构 / 计算机基础 / AI 工程 / 研发工程实践），每章标「基础 / 进阶 / 高级」，读完可直接跳到该章二级方向的专项练习（该二级方向题目不足时自动补充同方向题目）。
- 阅读进度按小节记录（本地、按账号隔离）：目录页有「继续学习」入口与每章进度，点进去直接落在上次读到的那一节。
- 文章页带章内目录：宽屏常驻右栏、窄屏折叠；当前小节随滚动高亮，读过的节打 ✓，点击即跳到该节锚点。

> **当前版本**：0.1.0，需求 `20261031-r1-dev-skill-coach` 交付四步闭环：上传解析 → 画像（每条带 `sourceQuote`、可逐条编辑）→ 模拟面试逐题评分 / 笔试题智判分 → 短板报告（证据可溯源 + 课程直链）→ 历史对比与 `.md` 导出。端点契约见 [TECHNICAL §2](./docs/teamflow/20261031-r1-dev-skill-coach/TECHNICAL.md)，架构见 [ARCHITECTURE](./docs/teamflow/architecture/ARCHITECTURE.md)。
>
> 任一尚未接通的端点返回 `501` + 统一中文错误 envelope（`{ "error": { code, message, retryable } }`），前端据此给出中文提示，不会白屏或 500。

## 快速开始（三步）

```bash
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

## Docker 部署（可选，一条命令起两容器）

不装 Python / Node 也能跑：`frontend`（nginx 托管构建产物 + 同源反代 `/api`、`/health`）+ `backend`（FastAPI，非 root、只在容器内网），数据落命名卷。

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

- **换端口**：把 `docker.env.example` 复制成仓库根 `.env`，改 `WEB_PORT=8080`，再 `docker compose up -d`。
- **建号（r23）**：`docker compose exec backend python -m app.admin_cli create-user --email me@example.com --mode own`（容器内执行，数据落在同名卷）。
- **停止**：`docker compose down`（**保留**数据卷）；`docker compose down -v` 会连数据一起删。
- **排障与运维**（lmstudio 本地档、备份恢复、502 / 413 / 504 排查）：见 [DEPLOY.md](./docs/teamflow/20261101-r10-docker-compose-deploy/DEPLOY.md)。

## 自检命令

| 位置 | 命令 | 期望 |
| --- | --- | --- |
| `backend/` | `python -m pytest -q` | 全部通过（AI 全链路注入 `FakeAI`，**零网络**） |
| `backend/` | `python -m ruff check app tests` | All checks passed |
| `frontend/` | `npm run typecheck && npm run lint && npm test && npm run build` | 无错误，生成 `frontend/dist/` |
| 根 | `curl -sS http://127.0.0.1:8000/health` | `{"status":"ok",...}` |
| 根 | `grep -riE "sk-\|api_key\|AI_API_KEY" frontend/src frontend/dist \|\| echo NO_KEY_LEAK` | `NO_KEY_LEAK`（AC-8） |

## 分支、交付与回滚

- **分支**：`feat/dev-skill-coach`，从基线提交 `32487b4` 起，本需求全部改动都在此分支上。
- **提交**：开发期间不留中间提交，也**不由 Agent 提交或合并**；验收通过后由流水线一次性提交（代码 + `docs/teamflow/` 任务夹一起入库，`?? docs/` 不会漏）。
- **回滚到基线（改动整体可撤销）**：

```bash
git reset --hard 32487b4 && git clean -fdx
```

  > `-fdx` 会连被忽略的 `node_modules/`、`frontend/dist/`、`.venv/`、本地 `*.db` 一起清掉；只想丢弃手改的代码、保留依赖时用 `git stash -u` 或 `git clean -fd`（保留 `-x` 的忽略项）。

### 不提交清单（`.gitignore` 已覆盖）

`node_modules/`、`dist/`、`frontend/.vite/`、`*.tsbuildinfo`、`__pycache__/`、`*.py[cod]`、`.venv/`（含 `backend/.venv/`）、`*.db` / `*.sqlite3`、`.env` 与 `.env.*`（**`backend/.env.example` 例外，必须提交**）、编辑器与系统目录，以及 TeamFlow 运行日志 `logs/teamflow/`（run 结束由 host 归档到 `$DSH_HOME`，不进仓库）。

## 目录

```
frontend/   React 18 + Vite 5 + TypeScript（5 步向导 + 学习 / 练习等工具页 + 设计 token）
backend/    FastAPI + SQLite（app/routers、app/services、app/seed）
docs/teamflow/   架构总览、产品记忆、每需求一个任务夹
```

## 安全边界（AC-8 / r23）

- 模型 Key 只出现在 `backend/.env`（内置 Key）；用户自带 Key 以 Fernet 密文存库，接口只回显后 4 位。
- 上传的简历**不落原文件**，只存抽取后的正文；错误响应不含路径、堆栈与模型端点。
- r23 起登录后才能使用：服务端会话 + HttpOnly Cookie（`sc_session`），6 张业务表按 `user_id` 隔离，
  跨用户按 id 取数一律 404；不开放注册，账号由管理员用 `app.admin_cli` 创建。

## 验收速览

闭环是否成立，按 PRD 的 AC-1 ~ AC-10 逐条走：上传 → 画像 → 面试/笔试 → 报告 → 课程。每条 AC 的验收证据、端点判分口径与错误码见任务夹 [TECHNICAL §2](./docs/teamflow/20261031-r1-dev-skill-coach/TECHNICAL.md) 与 `ACCEPTANCE.md`；后端测试全部注入 `FakeAI`，不依赖真实模型与外网即可复跑。
