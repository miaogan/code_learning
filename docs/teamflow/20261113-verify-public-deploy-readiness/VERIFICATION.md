# 公网部署就绪度验证（2026-11-13）

> 目标：**全面验证通路，为公网部署做准备**。不是一次「跑通就完」的冒烟，而是把
> 代码门禁 → 编排配置 → 真实容器栈 → TLS/安全头 → 登录与业务 API → 备份运维
> 整条链路按公网口径复跑，并明确列出还缺什么。
> 完整原始证据在 `logs/teamflow/verify-20261113/`（`logs/teamflow/` 已被 .gitignore 忽略）。

---

## 0. 结论

| 维度 | 结论 |
|---|---|
| 代码 / 测试 / 构建 | **就绪**。后端 910 用例 0 失败，前端 547 用例 0 失败，typecheck / lint / build / 5 个评测门禁 / 题库字节门禁全过，镜像从当前代码可构建。 |
| 生产叠加层（TLS + 安全头 + 生产档） | **就绪**。隔离演练栈端到端 **44/44 通过**（用最终重建镜像复跑仍 44/44）。 |
| 现在能不能直接上线 | **不能**。缺域名/DNS/服务器、真实 `backend/.env`、`deploy.env`、Let's Encrypt 证书与真实 AI Key；当前 `backend/.env` 是开发档，套上生产层会**拒绝启动**（已实测）。 |
| 本轮动作 | 修掉 **3 个直接影响公网的缺陷**（备份自检永久失败、公网 `/docs` 假绿、`/assets/` 双 Cache-Control 头）+ 修好本地半故障容器栈 + 22:30 追加修正 **3 项 P1 配置**（CI Python 版本、`WEB_PORT` 默认绑回环、Redis `maxmemory`），并同步所有示例/脚本/手册口径。改动清单见 §7。 |

---

## 1. 验证方法（可复现，且不碰用户现有栈）

用独立 compose 项目名 `scverify` 起一套**生产叠加层全真演练栈**：

```
基础层 docker-compose.yml
  + 生产层 docker-compose.prod.yml
  + 演练层 logs/teamflow/verify-20261113/verify.override.yml
  + 插值    logs/teamflow/verify-20261113/verify.env
```

- 演练层只做三件事：`backend.env_file` 换成无 Key 的演练配置（避免把宿主真实 Key 带进容器）、
  端口全绑回环并改高位（`18080` 模拟 80 / `18443` 模拟 443 / `18081` 调试口）、
  证书目录换成自签证书（**不污染项目根 `certs/`**，否则会挡住以后的 `cert.sh init`）。
- PostgreSQL 用 `scverify_skillcoach-pgdata` 独立卷，与用户现有 `code_learning_*` 卷完全隔离。
- 故意不配 AI Key：验证「AI 未就绪也不 500、`/health` 如实上报」，同时零配额消耗。
- `logs/teamflow/verify-20261113/verify_http.py` 是结构化验证脚本（44 项断言），
  `http-verify-final.log` 是最终结果。

---

## 2. 静态门禁

| 检查 | 结果 |
|---|---|
| `pytest -q`（真 PG，无 SQLite 兜底） | **910 tests / 0 failures / 0 errors / 1 skipped**，257s；JUnit：`logs/teamflow/verify-20261113/pytest.xml` |
| `ruff check app tests` | All checks passed |
| 题库字节门禁 `question_merge --check` | 1284 道逐字节一致（幂等成立） |
| 5 个离线评测 `--check` | 全过：30 例 schema 93.3% / micro-F1 98.5%；教程召回 ≥80%；题目侧 recall@5 **100%**；可靠性 +28.5pp；live dry-run 30 例 schema 96.7% |
| 前端 typecheck / lint | 全过，0 warning |
| 前端 `npm test` | **41 文件 / 547 测试全过**（`--pool=forks --maxWorkers=1 --minWorkers=1`） |
| 前端 `npm run build` | 成功；`dist` JS 796.57 kB / CSS 182.86 kB，仅 chunk >500 kB 提示（非阻断） |
| `npm audit --omit=dev --audit-level=high` | RC=0；2 条 moderate 属 `react-router` 6.x（README 已记录，升 7.x 为破坏性变更） |
| 前端凭据扫描 | 无真实 Key、无 `AI_*_API_KEY=` 赋值；命中的只是 `api_key` 字段名与 `task-min-h` 这类子串 |
| `pip-audit -r requirements.txt` | **本机未完成**：访问 PyPI advisory 超时（RC=124，75s 上限）。CI 该门禁历史通过（#117 全绿），目标服务器/CI 上需复跑 |
| `vitest` 并行跑的环境噪声 | 本机并行 worker 偶发 `EPERM ...\ssr\<hash>`（沙箱 fs shim），退出码 1 且个别文件不执行；**r83 已记录为已知环境问题**，串行跑稳定全量。非代码缺陷 |

> 构建镜像时，官方 `pypi.org` / `registry.npmjs.org` 在本机 >9 分钟未拉完。
> 改 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`、
> `NPM_REGISTRY=https://registry.npmmirror.com` 后前后端镜像数分钟内构建成功。
> 这两个值已是 compose 的 build args，部署机网络慢时直接传环境变量即可，不必改代码。

---

## 3. 配置与编排

| 检查 | 结果 |
|---|---|
| `docker compose -f 基础 -f 生产 --env-file deploy.env.example config` | RC=0。`backend/postgres/redis` **不发布宿主端口**；frontend `127.0.0.1:8080` + `0.0.0.0:80` + `0.0.0.0:443`；`APP_ENV=production` 生效；证书与 ACME webroot 只读挂载 |
| 当前 `backend/.env` + `APP_ENV=production` | **拒绝启动**：`COOKIE_SECURE 必须为 true`；另有 2 条 warning（CORS 仍含本机来源、DATABASE_URL 示例口令）。→ 见 §6 P0 |
| 生产模板（合成安全值） | `blockers=[]`、`warnings=[]` |
| 生产档不挂文档（单测 + 容器） | 后端确实 404；但**经 nginx 时曾是 200**，见 §5 缺陷 2 |
| `nginx -t`（生产 conf + 证书） | syntax ok / test is successful |
| 从当前代码构建镜像 | backend / frontend 均 Built；改完 `nginx.conf` 后又增量重建 frontend 一次，RC=0 |
| `./scripts/cert.sh`（无参数） | 打印用法并 `exit 2` |
| `./scripts/backup_db.sh` | 修复后 custom 与 plain 两种格式均 RC=0，`.dump` 自检读出 **118 条 TOC** |

---

## 4. 端到端 HTTP 通路（隔离栈，44/44）

**入口层**：HTTP `301` 跳 HTTPS；HTTPS `/health` 200 且 `db=postgresql`、`ai_configured=false`；
六项安全头（HSTS / nosniff / Referrer / Frame / Permissions / CSP）齐全且**无重复**；`/health` 带 `no-store`。

**文档与静态资源**：`/docs`、`/redoc`、`/openapi.json` 均 `404` 且 404 响应仍带安全头；
SPA 首页 200 且带全量安全头；`/assets/*.js` 只输出**一条** `Cache-Control: public, max-age=31536000, immutable`，
且该 location 的安全头未因自带 `add_header` 丢失。

**鉴权与边界**：未登录 `GET /api/me` → `401 {"error":{code,message,retryable}}`（中文）；
跨站 `Origin` 写请求 → `403 FORBIDDEN`；CORS 预检 → 200；
登录成功下发 `sc_session`，带 **Secure / HttpOnly / SameSite=Lax**；刷新后会话仍有效（Cookie → 会话表 → Redis 缓存链通）。

**业务通路**（登录后）：`/api/me`、`courses`、`learn/progress`、`practice/stats`、`practice/wrong-book`、
`interviews`、`radar/techs`、`radar/runs/latest`、`eval/summary`、`history?limit=200`（r93 修复点）、
`taifu/thread`、`taifu/memories` 全部 200；`profiles/latest` / `reports/latest` 无数据时 404 中文 envelope；
题目检索 POST 200；笔试集合 GET 405、空参数 POST 422 均为结构化中文错误，**全程无 500 / 无堆栈**。

---

## 5. 发现并修复的问题

### 缺陷 1（P0）· `scripts/backup_db.sh` 自检永久失败

`pg_restore -l - < dump` 里的 `-` 被 **PG16 当成文件名**（`could not open input file "-"`），
不是「从 stdin 读」。结果：`pg_dump` 产出的 `.dump` 其实完好（实测魔数 `PGDMP`、118 条 TOC），
脚本却每次都打「备份自检失败」并 `exit 1`。进 cron 后会天天红，运维要么忽略告警、
要么以为根本没有可用备份——**恢复当天才发现就晚了**。
修复：去掉位置参数 `-`（省略文件名才是读 stdin），并写注释钉住原因。
复验：`custom` RC=0 + 自检通过，`plain` RC=0。

### 缺陷 2（P1）· 公网入口 `/docs` 等返回 200（r97 验收假绿）

后端生产档确实没挂载 `/docs` / `/redoc` / `/openapi.json`，但 nginx 的 SPA fallback
（`try_files ... /index.html`）会把这些未知路径回落成首页并返回 **200**。
r97 手册 §4 明确要求 `curl https://<域名>/docs` 得 404，而 r97 验收记录是**直连后端**测的，
没经过 nginx，所以没照出这层差异。接口清单本身没泄漏（返回的是首页），但验收口径失真、
且路径语义不对。修复：`nginx.prod.conf` 加三个 `location = ... { return 404; }`（精确匹配优先于
`location /`），404 响应继承 server 层安全头。

### 缺陷 3（P1）· `/assets/` 输出两个 `Cache-Control` 头

`expires 1y;` 自己生成 `Cache-Control: max-age=31536000`，又叠加
`add_header Cache-Control "public, immutable"`，实测响应里两条同名头（语义靠浏览器合并兜着）。
修复：去掉 `expires`，用单条 `public, max-age=31536000, immutable`；
`nginx.prod.conf` 与内网 `nginx.conf` 同步改，保持两份路由/缓存口径一致。

### 文档滞后（r98 换 PG 后 r97 手册未同步）

| 文件 | 修正 |
|---|---|
| `docs/teamflow/20261112-r97-public-deploy/DEPLOY.md` | 备份/恢复从 SQLite `docker cp app.db` 改为 `pg_dump -Fc` / `pg_restore`；§8 边界从「SQLite + 单进程」改为「PG+Redis 但线上仍单副本」；排障表澄清「拒绝启动只拦 4 类，localhost CORS 仅告警」；新增「全新部署无需手工建表」；§2 补 `POSTGRES_PASSWORD` 必改；§7 补口令与 `.dump` 检查项 |
| `backend/.env.production.example` | 铁律 1 改成与实际一致的 4 类 blocker（原写「CORS 必须 https 否则拒启」是错的，`test_localhost_origin_only_warns` 明确只告警）；说明 `DATABASE_URL` 在容器内会被 compose 覆盖，真正口令来自 `deploy.env` |
| `deploy.env.example` | 修注释笔误；补「起栈必须带 `--env-file deploy.env`，否则默认 `0.0.0.0:8080` 会把明文入口暴露到公网」 |
| `README.md` | 基础镜像 `python:3.11-slim` → `python:3.13-slim`（与 `backend/Dockerfile` 一致） |

---

## 6. 上线前必须完成（按优先级）

### P0 · 没做就起不来 / 起得不安全

1. 准备：2 核 2G 起 Linux 服务器、已备案域名 `A` 记录解析到该机、安全组只放 **22 / 80 / 443**。
2. 后端生产配置（**替换当前开发档**）：
   ```bash
   cp backend/.env.production.example backend/.env && chmod 600 backend/.env
   # 必改：CORS_ORIGINS=https://<域名>、SECRET_KEY=$(openssl rand -hex 32)、AI_DEEPSEEK_API_KEY=<真实 Key>
   # 保持：APP_ENV=production / COOKIE_SECURE=true / REDIS_URL=redis://redis:6379/0 / RATE_LIMIT_ENABLED=true / BREAKER_ENABLED=true
   ```
3. compose 层配置：
   ```bash
   cp deploy.env.example deploy.env
   # 必改：PUBLIC_DOMAIN=<域名>、ACME_EMAIL=<邮箱>、
   #      POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
   # 保留：WEB_PORT=127.0.0.1:8080
   mkdir -p certs certbot/www backups
   ```
4. **必须先签证书再起栈**（nginx 缺证书文件直接启动失败，而 `cert.sh init` 要占 80）：
   ```bash
   ./scripts/cert.sh init
   docker compose -f docker-compose.yml -f docker-compose.prod.yml \
     --env-file deploy.env up -d --build          # ← --env-file 不能漏
   docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env \
     exec backend python -m app.admin_cli create-user --email you@example.com --name 你 --mode own
   ./scripts/backup_db.sh                          # 首份备份 + 自检
   ```
5. 按 [r97 手册 §4](../20261112-r97-public-deploy/DEPLOY.md) 逐条验收（本轮已用自签证书预演同样的 44 项）。
   浏览器侧再确认：Cookie 三个属性、刷新不掉线、上传 PDF 能生成画像、控制台无 CSP 报错。

### P1 · 建议上线前后补做

- 真实 Let's Encrypt 签发与 90 天续期（本轮**未验证**：本机无 DNS、无对外 80）。
- 配真实 AI Key 后跑一次完整闭环「上传 → 画像 → 面试/笔试 → 报告 → 教程」；
  本轮只验证了「无 Key 时 503 中文提示、不 500」。
- 备份进 cron（`10 3 * * * ... KEEP=14 ./scripts/backup_db.sh`），并做一次**恢复演练**
  （本轮只验证导出 + `pg_restore -l` 自检，未在空库做全量 `pg_restore`）。
- ~~CI 与生产 Python 版本不一致~~ **已于 22:30 修正**：`.github/workflows/ci.yml` 的
  `python-version` 由 `3.11` 改为 `3.13`，与 `backend/Dockerfile` 的 `python:3.13-slim` 同版。
  本机 Python 3.13.14 全量 910 用例 0 失败是兼容性证据；`ARCHITECTURE.md` 两处版本口径同步。
- ~~`WEB_PORT` 默认值 `0.0.0.0:8080`~~ **已于 22:30 修正**：`docker-compose.yml` 默认值收紧为
  `127.0.0.1:8080`（格式 `[绑定地址:]端口`）。连带改 `docker.env.example` / `deploy.env.example` /
  README / r10 DEPLOY / ARCHITECTURE / prod 注释，并修 `scripts/tunnel.sh`——否则
  `http://localhost:${WEB_PORT}` 会变成 `localhost:127.0.0.1:8080`。
- ~~用户当前**本地**栈处于半故障态~~ **已于 2026-11-13 22:23 修复**。根因：`backend` 容器停在
  `created`（从未启动、日志为空），Docker DNS 里没有 `backend` 记录，nginx 启动解析 upstream 失败
  即退出 → frontend 无限重启；叠加 redis 容器还是 7-alpine 的配置漂移。
  修法：`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate`
  （带 dev 覆盖层以保留宿主 5433 / 6380 端口给 pytest，配国内源加速构建；**未用 `down -v`**，数据卷保留）。
  复验：4 容器全 `running`、`RestartCount=0`，backend / PG / Redis 均 `healthy`；Redis 8.10.3；
  经 `http://127.0.0.1:8080` 的 `/health` 200（`ai_configured=true`、`db=postgresql`）、首页 200、
  `/assets/` 单条 Cache-Control、`/api/me` 401 中文 envelope；宿主直连 PG 5433 可连且
  `users=1 / questions=1284` 数据完好、Redis 6380 `+PONG`。日志见
  `logs/teamflow/verify-20261113/fix-local-stack.log`。
- ~~Redis 未设 `maxmemory`~~ **已于 22:30 修正**：`docker-compose.yml` 的 redis command 补
  `--maxmemory ${REDIS_MAXMEMORY:-128mb}`（可配置，默认 2C4G 单机口径），
  `deploy.env.example` / `docker.env.example` 给配置项，r98 DEPLOY.md 新增「Redis 内存上限」小节。
  实测 `CONFIG GET maxmemory = 134217728`、`maxmemory_human=128.00M`、policy `allkeys-lru`。
- `pip-audit` 在部署机/CI 上复跑一次（本机网络超时）。

---

## 7. 改动文件清单

| 文件 | 性质 |
|---|---|
| `scripts/backup_db.sh` | 修 P0 自检命令（去掉 `pg_restore -l` 后的 `-`）+ 注释 |
| `frontend/nginx.prod.conf` | 加 3 个文档路径 404；`/assets/` 单条 Cache-Control |
| `frontend/nginx.conf` | `/assets/` 同步单条 Cache-Control |
| `docs/teamflow/20261112-r97-public-deploy/DEPLOY.md` | r98 换库后的运维口径修正（6 处） |
| `backend/.env.production.example` | blocker 口径与 DATABASE_URL 覆盖说明 |
| `deploy.env.example` | 注释笔误 + 漏 `--env-file` 的暴露风险 |
| `README.md` | 基础镜像版本 3.11 → 3.13；换端口写法同步 |
| `docs/teamflow/20261113-verify-public-deploy-readiness/VERIFICATION.md` | 本报告 |

**22:30 追加的 P1 修正**（同一份就绪度任务的第二批改动）：

| 文件 | 性质 |
|---|---|
| `.github/workflows/ci.yml` | CI Python `3.11` → `3.13`，与容器镜像同版 |
| `docker-compose.yml` | `WEB_PORT` 默认值收紧为 `127.0.0.1:8080`；Redis 补 `--maxmemory ${REDIS_MAXMEMORY:-128mb}`；头部 PG 卷名注释纠错 |
| `docker.env.example` / `deploy.env.example` | 端口格式说明、`REDIS_MAXMEMORY` 配置项、漏 `--env-file` 的风险提示 |
| `docker-compose.prod.yml` | 端口默认值注释同步 |
| `scripts/tunnel.sh` | 从 `WEB_PORT` 提取端口（兼容 `host:port`），并避开 `set -u` 下未定义变量 |
| `docs/teamflow/architecture/ARCHITECTURE.md` | Python 版本、CI 版本、`WEB_PORT` 三处口径 |
| `docs/teamflow/20261101-r10-docker-compose-deploy/DEPLOY.md` | 端口契约表 / 最短路径 / 排障表同步 |
| `docs/teamflow/20261112-r98-redis-pg/DEPLOY.md` | 新增「Redis 内存上限」小节与自检命令 |
| `docs/teamflow/memory.md` | 记录三条现行口径 |

**修正后的验证**：三种 compose 组合 `config` 均 RC=0（基础 / dev 端口 `127.0.0.1:8080`；
prod 另外 `0.0.0.0:80/443`；redis command 均含 `--maxmemory 128mb`）；CI YAML 解析出
`python-version=3.13`；`bash -n scripts/tunnel.sh` 通过，端口提取矩阵
（未设置 / `8081` / `127.0.0.1:8080` / `127.0.0.1:8099` / `0.0.0.0:9000`）全部正确；
重建 redis + frontend 后实测 `maxmemory=134217728`、`maxmemory_human=128.00M`、
policy `allkeys-lru`、frontend 实际绑定 `127.0.0.1:8080`、`/health` 与首页均 200、
`users=1 / questions=1284` 数据完好、4 容器全部 healthy；后端按 3.13 复跑 `pytest`：
**910 / 0 failures / 0 errors / 1 skipped**（JUnit `pytest-p1.xml`），`ruff` All checks passed。
该次 shell 收尾退出码被沙箱 `safe-delete` 钩子污染成 1（r83 与前次验证均有同类记录，
进度线无 F/E、JUnit 无 failure 节点，非测试失败）；把 `TMP` 指到工作区后重跑可得 RC=0。

> 仍未改：`production_blockers()` 行为（`localhost` CORS 只告警是
> `test_r97_production_guard.py` 明确钉住的设计，改文档而非改代码）；
> 真实证书 / AI Key / 域名属外部输入，不属代码修正范围。

---

## 8. 已知边界（没有验证到的，不要当成已完成）

- 真实域名证书签发 / 续期、真实模型调用与配额、多副本与滚动升级、CDN / WAF / DDoS、
  异地备份、CI 远端执行、移动端浏览器。
- 单副本 uvicorn 仍是当前形态；r98 的 PG + Redis 提供了共享状态基础，但多副本未实跑验证。
- 所有评测指标来自合成数据 / 模拟故障，只用于回归检测，不代表生产 QPS 或模型质量。
- 隔离演练栈在验证完成后已 `down -v` 清理（只删 `scverify_*` 卷，不动用户数据卷）。

## 9. 复现命令

```bash
# 静态门禁
cd backend && .venv/Scripts/python -m pytest -q --junitxml=../logs/teamflow/verify-20261113/pytest.xml
cd frontend && npm run typecheck && npm run lint && npm test -- --maxWorkers=1 --minWorkers=1 && npm run build

# 编排校验（不输出任何 Key）
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env.example config

# 隔离演练栈
docker compose -p scverify -f docker-compose.yml -f docker-compose.prod.yml \
  -f logs/teamflow/verify-20261113/verify.override.yml \
  --env-file logs/teamflow/verify-20261113/verify.env up -d --build
backend/.venv/Scripts/python -X utf8 logs/teamflow/verify-20261113/verify_http.py
```
