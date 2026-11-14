# DEPLOY · SkillCoach 容器化部署与运维（r10）

> 服务形态：`浏览器 → frontend(nginx:80，宿主 ${WEB_PORT:-127.0.0.1:8080}，默认只绑回环) → /api、/health → backend:8000（仅容器内网）`
> 本页面向「部署 / 排障 / 切换模型档位」；首次启动的最短路径也在这里，README 只放三步摘要。

## 0. 契约单源（改任一项必须三处同改）

| 契约 | 值 | 出现位置（同改清单） |
| --- | --- | --- |
| 服务名 | `backend` / `frontend` | `docker-compose.yml`、`frontend/nginx.conf`（`proxy_pass http://backend:8000`）、本页、`README.md` |
| 后端端口 | `8000`（**不发布到宿主**） | `backend/Dockerfile`（`EXPOSE`/`CMD`）、`frontend/nginx.conf`、`docker-compose.yml`（command + healthcheck） |
| 宿主端口 | `${WEB_PORT:-127.0.0.1:8080}`（格式 `[绑定地址:]端口`，换端口时别丢绑定地址） | `docker-compose.yml`、本页、`README.md` |
| 数据卷 | `skillcoach-data:/data`（实际卷名 `<项目名>_skillcoach-data`，本仓库 = `code_learning_skillcoach-data`） | `docker-compose.yml`、本页 |
| 配置来源 | `backend/.env`（compose 用 `env_file` **引用**，`required:false`） | `docker-compose.yml`、`docker.env.example`、本页 |
| 健康探针 | `GET /health`（python urllib，slim 无 curl） | `backend/Dockerfile` 的 `HEALTHCHECK` 与 `docker-compose.yml` 的 `healthcheck`（命令逐字相同，仅 interval/start_period/retries 可不同） |

配套文件：`docker.env.example`（示例配置，人工复制）、`frontend/nginx.conf`（反代 + 静态托管）、两个 `.dockerignore`（构建上下文裁剪）。

## 1. 最短路径（三步）

```bash
# 1) 准备配置：backend/.env 是容器唯一的配置来源，需在其中填上真实 AI_DEEPSEEK_API_KEY
#    首次部署（还没有 backend/.env）：照 docker.env.example 建一份，再填 Key
copy docker.env.example backend\.env       # macOS/Linux: cp docker.env.example backend/.env
#    已有 backend/.env：只手工补 AI_DEEPSEEK_API_KEY / AI_PROVIDER 两个键，**别覆盖原文件**
#    其余后端键（上传上限、legacy 三件套、AI_LMSTUDIO_*）以 backend/.env.example 为唯一出处
#    想换宿主端口：把 docker.env.example 复制成仓库根 .env，改 WEB_PORT=127.0.0.1:8099
#    （必须带绑定地址；只写 8099 会绑 0.0.0.0，明文口暴露到局域网/公网）

# 2) 构建并启动（首次约数分钟，后面走层缓存）
docker compose up -d --build

# 3) 打开 http://127.0.0.1:8080
#    /health 自检见第 2 节；down 停止；改 WEB_PORT 后重新 up 即可换端口
docker compose ps          # 两个服务都应是 running，backend 的 STATUS 带 (healthy)
```

- `docker compose down` **保留**命名卷（数据在）；`docker compose down -v` 才会删卷（**数据一并消失**）。
- `AI_DEEPSEEK_API_KEY` 留空也能起：`/health` 会如实报 `ai_configured=false`，页面给中文提示，不 500。
- 只重建某一侧：`docker compose up -d --build backend`（或 `frontend`）。

## 2. 健康检查与就绪口径

```bash
curl -sS http://127.0.0.1:8080/health
# {"status":"ok","version":"...","ai_configured":true,"db":"sqlite",
#  "ai_provider":"legacy|deepseek|lmstudio","ai_model":"deepseek-chat","ai_json_mode":"..."}
docker compose ps        # backend: (healthy) 才算就绪；frontend 等 backend healthy 才启动
```

读法（**探针只认 HTTP 200，`healthy` ≠ AI 已配好**）：

- `status` 恒为 `ok`，`db` 恒为 `sqlite`（SQLite 落在卷内 `/data/app.db`）。
- `ai_configured` 才是「AI 链路是否可用」：`true` = Key 有效、可调真实模型；`false` = 未配 Key（功能不崩，提示中文）。
- `ai_provider` 的判定优先级（**唯一权威**，compose `command` 里推导，不进业务代码）：
  1. `backend/.env` 里显式 `AI_PROVIDER` 非空 → 照它来（`deepseek` / `lmstudio`）；
  2. 否则 `AI_DEEPSEEK_API_KEY` 非空 → 自动 `deepseek`；
  3. 否则保持空 = `legacy` 三件套（`AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL`）。
- **`ai_provider=legacy` 是正常形态**：它表示走 legacy 三件套（现有 `.env` 就指向 `https://api.deepseek.com/v1`），
  `ai_configured=true` 时链路完全可用。看到 `legacy` 不要去「修」。
- `healthy` 的判据是 `GET /health` 返回 200（未配 Key 也 200），所以 healthy 只代表进程与库可用。

看容器内实际解析结果（`repr` 已挡住 Key，不会打印凭据）：

```bash
docker compose exec backend python -c "from app.config import get_settings; r=get_settings().resolve_ai(); print(r.provider, r.model, r.ready, r.reason)"
docker compose exec backend sh -c 'test -n "$AI_DEEPSEEK_API_KEY" && echo KEY_SET || echo KEY_MISSING'
```

> ⚠️ 不要用 `docker compose config` 排查配置：它会把 `backend/.env` 展开成纯文本打印（**含真实 Key**），
> 只在本地终端看、绝不贴进日志/工单/聊天。

## 3. 日志

```bash
docker compose logs -f backend        # 后端（uvicorn 访问日志 + lifespan + 报错栈）
docker compose logs -f frontend       # nginx（反代 502/504、413 等都在这里）
docker compose logs --tail=200 backend
docker compose exec backend sh -c 'ls -l /data'   # 卷内文件与属主（app:app 才对）
```

## 4. 切换 lmstudio（本地大模型档，r9 引入）

Docker Desktop（Windows/macOS）自带 `host.docker.internal`；Linux 需显式给 `extra_hosts`。

```bash
# backend/.env 追加/修改（其余 AI_LMSTUDIO_* 清单照抄 backend/.env.example，唯一可信出处）
AI_PROVIDER=lmstudio
AI_LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1
AI_LMSTUDIO_MODEL=qwen3.5-9b
AI_LMSTUDIO_JSON_MODE=none
AI_LMSTUDIO_API_KEY=
AI_LMSTUDIO_TIMEOUT_S=600

# 改了 .env 必须重建容器（env_file 在 create 时读取，restart 不会重读）
docker compose up -d --force-recreate backend
curl -sS http://127.0.0.1:8080/health   # 期望 ai_provider=lmstudio
```

Linux 若报连接被拒，在 `docker-compose.yml` 的 `services.backend` 下放开这行（本仓库默认注释掉，不默认改拓扑）：

```yaml
    # extra_hosts:
    #   - "host.docker.internal:host-gateway"
```

另外：LM Studio 的服务默认只监听 `127.0.0.1:1234`，需在 LM Studio 里开启「Serve on Local Network」（监听 `0.0.0.0`），
否则容器侧一律 connection refused。**AI 长请求超时**：nginx 已把 `/api`、`/health` 的
`proxy_read_timeout` / `proxy_send_timeout` 放到 `1300s`（= 600s × (1 + 重试 1) 的余量），别改小回默认 60s，否则本地模型必然 504。

## 5. 数据备份与恢复

容器化后数据在**命名卷内** `/data/app.db`（可能有 `-wal` / `-shm` 伴随文件）；
宿主 `backend/app.db` **不自动迁移**进卷，卷里的数据也**不会**自动写回宿主——两边互不影响。

**备份**（先停后端保证库一致）：

```bash
docker compose stop backend
docker compose cp backend:/data/app.db ./app.db.bak        # 二进制安全，别用 cat/重定向
docker compose start backend
```

**恢复**（会**覆盖**当前卷内库；先确认 `./app.db.bak` 是你想要的版本，禁止脚本化自动覆盖）：

```bash
docker compose stop backend
docker compose cp ./app.db.bak backend:/data/app.db
# cp 进去的文件属主是 root，非 root 的 app 用户写不了 → 必须纠正属主，否则启动即 EACCES
docker compose run --rm -u root backend chown -R app:app /data
docker compose up -d backend && docker compose ps backend
```

**把宿主旧库人工搬进卷**（仅全新部署、卷内还没有数据时手动执行一次）：

```bash
docker compose up -d backend
docker compose cp backend/app.db backend:/data/app.db
docker compose run --rm -u root backend chown -R app:app /data
docker compose restart backend
```

## 6. 故障排查

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| 页面打开但接口全 502（backend 明明在跑） | nginx 在**配置加载时**解析 `backend` 的 Docker DNS 并缓存；backend 被单独 recreate 换了 IP | `docker compose restart frontend` 刷新解析。（**不要**把 `proxy_pass` 改成变量——会破坏 URI 前缀语义） |
| backend 一直 `(health)` 起不来 / 日志里 `sqlite3.OperationalError: unable to open database file`（EACCES） | `/data` 属主不对：镜像里 `chown` 必须在 `USER app` **之前**，命名卷首次挂载继承该属主 | 先看 `docker compose logs backend`；旧卷修属主：`docker compose run --rm -u root backend chown -R app:app /data && docker compose restart backend`。**不要** `chmod 777`，也**不要**改成 root 运行 |
| frontend 起不来 / 整栈卡在 `backend: waiting` | `depends_on: service_healthy` 门控：backend 探针没过，前端就不会启动 | 先修 backend（上方两行），`docker compose ps` 见 healthy 后前端自动起 |
| 端口被占（8080 已有服务）/ `Bind for 127.0.0.1:8080 failed` | 宿主 8080 冲突（本机常见 8000 是本地 uvicorn、5432 是 ldt-postgres，故 backend 不发布端口） | 改 `WEB_PORT`（根 `.env` 或环境变量），如 `WEB_PORT=127.0.0.1:8081 docker compose up -d`，再访问 `http://127.0.0.1:8081` |
| 上传 10–20MB 文件返回 **HTML 413** 而不是 JSON envelope | 双层上限：`frontend/nginx.conf` 的 `client_max_body_size 20m` 必须**严格大于**应用侧 `MAX_UPLOAD_MB=10`；nginx 先拦就会返回 HTML | 保持 nginx > 应用（默认 20m > 10m 即正确）；调应用上限时同步调 nginx，改完 `docker compose up -d --build frontend` |
| AI 请求约 60s 后 504（`upstream timed out`） | 反代超时被改回 nginx 默认 60s；r9 lmstudio 单次画像实测 201–224s | 恢复 `/api`、`/health` 的 `proxy_read_timeout` / `proxy_send_timeout` 为 `1300s`，重建 frontend |
| `ai_configured=false` | `backend/.env` 没 Key，或改了 `.env` 没重建容器（env_file 只在 create 时读） | 填 Key → `docker compose up -d --force-recreate backend` |
| 发布新版本后浏览器还是旧页面 | `index.html` 已设 `no-cache`、`/assets/` 是 immutable，但旧标签页/强缓存仍可能吃旧壳 | 硬刷新一次（Ctrl+F5）；确认 `docker compose ps` 里 frontend 是新镜像 |

## 7. 文档差异记录（本轮白名单外，未改）

`docs/teamflow/architecture/ARCHITECTURE.md:279` 的部署表仍写着「Docker 打包 / 一键启动脚本 | 未做（README 为三步手动流程） | 后续」。
本轮（r10）已交付 `docker-compose.yml` + 两个 Dockerfile + nginx 反代，**该行已与实际不符**；
但 `docs/teamflow/architecture/` 在本需求改动白名单之外，故仅在此记录差异，由后续需求回写架构文档。
同一份白名单还导致 `docs/teamflow/memory.md` 的「容器化交付约定」里仍保留「`.gitignore` 需追加 `!.env.docker.example`」一句——
示例文件最终命名为 `docker.env.example`（`.env.*` 不匹配它，`git check-ignore` 实测未命中），`.gitignore` 零改动，该句同样待后续需求订正。
