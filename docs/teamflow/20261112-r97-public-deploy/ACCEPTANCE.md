# r97 公网部署准备 · 验收

## §1 交付内容

| 文件 | 作用 |
|---|---|
| `backend/app/core/config.py` | 新增 `app_env`、`is_production`、`production_blockers()`、`production_warnings()` |
| `backend/app/main.py` | 启动前校验（不安全即拒绝启动）；生产档关闭 `/docs` `/redoc` `/openapi.json` |
| `backend/tests/test_r97_production_guard.py` | 11 条：档位、阻断、告警、文档开关 |
| `frontend/nginx.prod.conf` | TLS 入口：80 只为 ACME + 301；443 终结 TLS 并沿用既有路由表 |
| `frontend/security-headers.conf` | 六个安全响应头的单点定义（含「location 有 add_header 会丢父级头」的 include 处理） |
| `docker-compose.prod.yml` | 生产覆盖层：`APP_ENV=production`、80/443、证书与 webroot 挂载、日志滚动 |
| `backend/.env.production.example` | 生产后端配置模板（CORS/Cookie/SECRET_KEY/限流/AI） |
| `deploy.env.example` | compose 层变量（`WEB_PORT=127.0.0.1:8080`、域名、ACME 邮箱） |
| `scripts/cert.sh` | `init`（standalone 首次签发）/ `renew`（webroot 续期 + reload） |
| `scripts/backup_db.sh` | SQLite 在线备份（`Connection.backup`）+ `quick_check` 自检 + 滚动保留 |
| `.gitignore` | `certs/` `certbot/` `backups/` `deploy.env` 忽略；放行 `!.env.production.example` |
| `docs/teamflow/20261112-r97-public-deploy/DEPLOY.md` | 上线顺序、验收命令、运维 cron、排障表、安全清单、已知边界 |

## §2 关键设计

**为什么校验要「拒绝启动」而不是只告警**：公网部署里 `COOKIE_SECURE=false` 不会报错，
只会让会话 Cookie 在 http 上明文传输——这种错**运行时完全看不出来**，只能靠启动期拦。
而「限流被关」「SECRET_KEY 没设」是可用性/功能降级，拦人反而挡排障，所以只 WARNING。
两档语义在 `production_blockers()` / `production_warnings()` 里分开，单测逐条钉住。

**为什么安全头要单独一个文件并反复 include**：nginx 的 `add_header` 是「本层有就不继承父级」，
而 `/assets/`、`/api/`、`/health`、`/index.html` 各自都有 `Cache-Control` —— 不显式 include
就会在这些 location 上静默丢掉全部安全头。实测 `/health`（502 时）仍带 HSTS 与 nosniff。

**为什么 CSP 允许 `style 'unsafe-inline'`**：React 的 `style={{}}` 是内联样式属性，去掉会白屏；
`script-src` 保持严格 `'self'`（`index.html` 只有外链 module，无内联脚本）。

**为什么先签证书再起栈**：`ssl_certificate` 指向的文件不存在时 nginx 直接启动失败，
而 `cert.sh init` 需要 80 空闲 —— 顺序反了会陷入「起不来 → 签不了 → 更起不来」。

## §3 验证记录

| 检查 | 结果 |
|---|---|
| `pytest tests/test_r97_production_guard.py` | 11 passed（档位 5 + 告警 3 + 文档开关 2 + 生产就绪 1） |
| 后端全量 `pytest -q` / `ruff check app tests` | 全绿 / All checks passed |
| 生产档容器（真实镜像）拒绝启动 | `APP_ENV=production` 无 `COOKIE_SECURE` → `RuntimeError: 生产环境配置不安全，已拒绝启动：COOKIE_SECURE 必须为 true…`，进程退出 |
| 生产档容器（真实镜像）正常启动 | `/docs` 404、`/redoc` 404、`/openapi.json` 404、`/health` 200；日志两条 `production.config_warning`（SECRET_KEY 空、AI 未就绪） |
| nginx 配置（真实 TLS 版，非默认 conf） | `nginx -t` successful |
| 80 端口 | `HTTP/1.1 301 Moved Permanently` |
| 443 端口 | `200`，响应头含 HSTS / nosniff / Referrer-Policy / X-Frame-Options / Permissions-Policy / CSP（逐条核对） |
| `/health`（后端未起，502） | 仍带 HSTS + nosniff + Cache-Control: no-store → 证明 location 级 include 生效 |
| `docker compose -f … -f … config` | 合并成功：80/443 对外，8080 由 `WEB_PORT=127.0.0.1:8080` 绑回环 |
| `scripts/backup_db.sh` | 真实跑通：`quick_check = ok`、5.5MB、31 张表、`reports` 4 行 |
| `scripts/cert.sh`（无参数） | 打印用法并 `exit 2` |
| 前端 | 零改动 |

**验证中发现并修掉的问题**：首次用 Git Bash 挂载校验 nginx 配置时，`$PWD` 的 `D:/…` 被
MSYS 当成路径转换、`docker cp` 的容器内绝对路径也被改写，导致「配置校验通过」实际校验的是
镜像自带默认 conf（假绿）。改为 `MSYS_NO_PATHCONV=1` + `docker cp` 后才拿到真结果。
同一坑在验证生产档时又出现一次：`-e DB_PATH=/data/prod.db` 被改写成 `E:/…/data/prod.db`，
SQLite 报 `unable to open database file`，看起来像应用 bug，实际是 shell 层的路径转换。
两条都已写进本文，避免下次再被同一个坑骗过。

## §4 风险与边界

- **SECRET_KEY 与 AI Key 只在 `backend/.env`**：本轮没有把密钥搬进任何新位置，`deploy.env` 零密钥；
- **既有开发流程零变化**：不设 `APP_ENV` 时两个校验方法恒返回空列表（单测 AC-4 钉住）；
- **`APP_ENV=production` + 旧 `backend/.env` 会拒绝启动**——这是**故意**的：直接沿用内网 .env
  上公网时，用户会看到明确的中文原因，而不是「上线后登录莫名掉线」；
- **单副本 / 无 WAF / 备份在本机**：写进 DEPLOY.md §8，不当成已完成能力；
- **证书脚本未在真实域名上跑过**：本机无 80 端口可对外、无 DNS，`init` 分支只验证了参数与前置检查，
  Let's Encrypt 实际签发需在目标服务器执行一次。
