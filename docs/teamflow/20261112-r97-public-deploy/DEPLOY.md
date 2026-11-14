# 公网部署手册（r97）

> 目标读者：第一次把「逃跑计划」放到公网的人。
> 本文只讲**公网**这一步；内网 compose、lmstudio 切换、413/504 排查见
> [r10 DEPLOY.md](../20261101-r10-docker-compose-deploy/DEPLOY.md)。

## 0. 一句话结论

内网那套 `docker compose up -d` 不能直接上公网：它只监听 80、没有 TLS、Cookie 不带 Secure，
且 `backend/.env` 还是开发值（CORS 指向 localhost）。r97 补的是一条**能安全暴露到公网**的路径：

| 层 | 之前 | 现在（r97） |
|---|---|---|
| 入口 | nginx :80，纯 http | :443 TLS 终结，:80 只留 ACME + 301 跳转 |
| 响应头 | 无 | HSTS / nosniff / Referrer / Frame / Permissions / CSP |
| 接口清单 | /docs、/openapi.json 公开 | 生产档直接不挂载（404） |
| 配置 | 生产/开发不分 | `APP_ENV=production` 启动前校验，不安全就**拒绝启动** |
| 运维 | 无 | 证书签发/续期脚本、PG 逻辑备份脚本（r98 起不再是 SQLite 数据卷拷贝） |

应用层本来就有：scrypt 口令、会话只存 SHA-256 摘要、HttpOnly+SameSite Cookie、同源写请求校验、
按 IP 限流、在飞请求熔断、登录失败锁定。**这些不需要额外做，但不要在 deploy.env 里把它们关掉。**

## 1. 前置条件

- 一台 2 核 2G 起的 Linux（Windows 宿主机同样可用，只是证书脚本里的 `-p 80:80` 需要 Docker Desktop）；
- 已备案域名（大陆服务器）解析到该机器：`A @ -> <IP>`、`A www -> <IP>`，等 DNS 生效；
- 安全组/防火墙放行 **80 / 443**；**不要**放行 8080；
- Docker + Compose v2（`docker compose version` 可用）。

## 2. 一次性准备（3 个文件）

```bash
git clone <repo> && cd code_learning

# ① 后端生产配置（唯一来源，权限收紧）
cp backend/.env.production.example backend/.env
chmod 600 backend/.env
#   必改：CORS_ORIGINS=https://<你的域名>、SECRET_KEY=$(openssl rand -hex 32)、AI_DEEPSEEK_API_KEY=<真实 Key>
#   COOKIE_SECURE 已是 true，不要改回 false

# ② compose 层变量（端口与域名，不含任何 Key）
cp deploy.env.example deploy.env
#   必改：PUBLIC_DOMAIN=<你的域名>、ACME_EMAIL=<你的邮箱>、POSTGRES_PASSWORD=<强口令>
#   保留 WEB_PORT=127.0.0.1:8080（只绑回环，供本机排障）
#   POSTGRES_PASSWORD 由 compose 同时拼给 postgres 服务与后端 DATABASE_URL，
#   是唯一生效的口令来源（backend/.env 里那行 DATABASE_URL 会被 compose 覆盖）。

# ③ 证书与备份目录（compose 会挂载它们）
mkdir -p certs certbot/www backups
```

## 3. 首次上线（顺序不能颠倒）

```bash
# 3.1 先签证书：此时 80 端口还空着，用 standalone 验证最省事
./scripts/cert.sh init          # 成功后 certs/ 下出现 fullchain.pem / privkey.pem

# 3.2 起整栈（生产覆盖层 + deploy.env 插值）
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file deploy.env up -d --build

# 3.3 建账号（注册不开放，账号只能由管理员创建）
docker compose exec backend python -m app.admin_cli create-user \
  --email you@example.com --name 你的名字 --mode own
#   终端会打印一次性初始密码；--mode own = 用户自带 Key，shared = 共用服务端 Key
```

**为什么先签证书**：nginx 在 `ssl_certificate` 指向的文件不存在时会直接启动失败，
而 `cert.sh init` 需要 80 端口空闲——所以顺序是「签证书 → 起栈」，不是反过来。
已有证书的机器跳过 3.1，直接 3.2。

全新部署无需手工建表：backend 启动时 `init_db()` 会建表并幂等导入题库种子。
从 r97（SQLite）升级的机器才需要迁移，步骤见
[r98 迁移手册](../20261112-r98-redis-pg/DEPLOY.md) §3，**不要**把旧 `app.db` 直接拷进容器。

## 4. 上线验收（逐条打勾，别跳）

```bash
curl -sI http://<域名>/ | head -1                 # 期望 301
curl -sI https://<域名>/ | grep -i strict          # 期望 HSTS 头
curl -s -o /dev/null -w '%{http_code}\n' https://<域名>/docs      # 期望 404
curl -s -o /dev/null -w '%{http_code}\n' https://<域名>/openapi.json  # 期望 404
curl -s https://<域名>/health                     # 期望 {"status":"ok",...}
```

浏览器侧再确认四件事：

1. 登录成功 → DevTools → Application → Cookies：`sc_session` 带 **Secure / HttpOnly / SameSite=Lax**；
2. 刷新页面仍是登录态（说明 Cookie 与 CORS 配对了）；
3. 上传一份 PDF 简历，画像能生成（说明反向代理长超时与 AI 配置都通）；
4. 控制台无 CSP 报错（有的话先看是不是引入了外链资源，而不是直接放宽 CSP）。

## 5. 日常运维

**备份（强烈建议 cron，每天一次）**

r98 起数据层是 PostgreSQL，脚本改为 `pg_dump -Fc` 一致性逻辑备份（不再是 r97 的
SQLite `app.db` 在线拷贝）：产出 `backups/app-<时间戳>.dump`，并用 `pg_restore -l`
自检归档可读。**照 r97 旧命令去 `docker cp app.db` 是无效备份**——backend 容器已不挂 `/data`。

```bash
./scripts/backup_db.sh                 # → backups/app-<时间戳>.dump + pg_restore -l 自检
# crontab -e
# 10 3 * * * cd /srv/code_learning && KEEP=14 ./scripts/backup_db.sh >> backups/backup.log 2>&1
```

恢复：`docker compose stop backend` →
`docker compose exec -T postgres pg_restore -U postgres -d sc_app --clean --if-exists < backups/app-xxx.dump`
→ `docker compose start backend`。**恢复前先把当前库另存一份**，别在唯一副本上操作。
只恢复单表用 `pg_restore --table=<表名> --data-only`；完整命令见
[r98 运维手册](../20261112-r98-redis-pg/DEPLOY.md) §5。Redis 只存可重建的限流 / 缓存 / 锁，不需要备份。

**证书续期（Let's Encrypt 90 天）**

```bash
# crontab -e（每月 1 号凌晨，走 webroot 不停服）
# 30 3 1 * * cd /srv/code_learning && ./scripts/cert.sh renew >> certbot/renew.log 2>&1
```

**升级**

```bash
git pull && ./scripts/backup_db.sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env up -d --build
curl -s https://<域名>/health
```

数据库变更全部是「建表 / 补列」的幂等 DDL，升级不需要手工迁移；
但**回滚旧版本前必须先备份**——旧代码不认识新列，不会自动降级。

## 6. 排障对照表

| 现象 | 大概率原因 | 处理 |
|---|---|---|
| 后端容器反复重启，日志有「生产环境配置不安全，已拒绝启动」 | `backend/.env` 还是开发值 | 按日志点名的项改：**拒绝启动只拦 4 类**（`COOKIE_SECURE=false`、`CORS_ORIGINS` 含 `*` 或为空、`REDIS_URL` 为空）；`CORS_ORIGINS` 仍是 `http://localhost` 只产生 `production.config_warning`，不会拒启，但公网必须改成 https 域名否则写请求 403 |
| 页面能打开，登录「成功」但立刻掉线 | Cookie 没下发（http 访问 / Secure 不匹配）或 CORS 不含当前域名 | 确认走 https；`CORS_ORIGINS` 与地址栏域名逐字一致（含 www 与否） |
| 写操作 403「请求来源不被允许」 | 域名换了没改 CORS | 补 `CORS_ORIGINS` 并重启 backend |
| 上传报 413 | nginx `client_max_body_size` 小于应用上限 | 保持 nginx 20m > `MAX_UPLOAD_MB=10`，不要只改一侧 |
| 长任务 504 | 反代超时被改短 | `proxy_read_timeout` 必须保持 1300s（本地模型链路） |
| 429 频繁 | 限流窗口过紧 / 多人同一出口 IP | 调 `RATE_LIMIT_API_PER_WINDOW`；若挂了 CDN，见下条 |
| 所有人都被限成同一个 IP | 前面又加了一层反代（CDN） | 让 CDN 回源带 `X-Forwarded-For`，并确认 nginx 的 `X-Real-IP` 覆盖逻辑 |
| 证书续期失败 | 80 未放行 / webroot 路径不对 | `./scripts/cert.sh renew` 手工跑一次看 certbot 输出 |

## 7. 安全清单（上线后每月看一次）

- [ ] `backend/.env` 权限 600，且没有第二份副本散落在仓库/聊天记录里；
- [ ] `SECRET_KEY` 已设置（用户自带 Key 才会加密存储）；
- [ ] `deploy.env` 的 `POSTGRES_PASSWORD` 已换成强口令——启动期告警只识别
      `postgres:postgres` 这一种示例口令，换成别的示例串不会告警；
- [ ] 备份产物是 `.dump`（`pg_dump -Fc`）而非 `.db`，且 `./scripts/backup_db.sh` 进 cron；
- [ ] `RATE_LIMIT_ENABLED`、`BREAKER_ENABLED` 保持 true；
- [ ] 账号只有该有的人有（`admin_cli list`），离职/试用结束及时 `disable`；
- [ ] `backups/` 与 `certs/` 不进 git、不进静态目录、备份文件按需加密后异地存一份；
- [ ] 服务器只开 22 / 80 / 443，8080 绑在回环。

## 8. 已知边界（不是 bug，是当前形态）

- **单副本**：r98 起数据层已是 PostgreSQL + Redis（共享限流 / 会话缓存 / 分布式锁），但线上仍是**单副本 uvicorn**；多副本部署与滚动升级未实跑验证，扩容前先做一轮；
- **无 WAF / 无 CDN**：常见扫描与暴力破解靠限流 + 登录锁定挡住，不挡 DDoS；
- **无审计日志导出**：`ai_call_logs` 只用于配额与排障，没有面向合规的导出；
- **备份在本机**：脚本只保证「有一份可用的库」，异地容灾要自己接对象存储。
