# r97 · 公网部署准备

## 1. 背景

r10 起有两容器部署（nginx 同源反代 + FastAPI + 命名卷），但它是**内网形态**：

- 只监听 80，没有 TLS —— 会话 Cookie 走明文，密码虽经 HTTPS 之外的通道也会裸奔；
- `backend/.env` 是开发值（`CORS_ORIGINS` 指向 localhost、`COOKIE_SECURE=false`）；
- `/docs`、`/redoc`、`/openapi.json` 默认公开，等于把接口清单交给扫描器；
- 没有任何安全响应头；没有证书签发/续期、没有数据库备份的固定做法。

应用层的安全基线其实已经在了（scrypt、会话只存摘要、HttpOnly+SameSite、写请求同源校验、
按 IP 限流、在飞熔断、登录锁定）。缺的是**入口层与运维路径**。

## 2. 目标

1. 一条可复制的公网部署路径：`签证书 → 起栈 → 建号 → 验收`；
2. 生产配置错了要**当场失败**，而不是带病上线（`APP_ENV=production` 启动校验）；
3. 公网入口带 TLS + 全站安全响应头，生产档不暴露接口文档；
4. 数据与证书有明确的备份/续期脚本，不靠人记；
5. 开发/内网流程**零变化**：不设 `APP_ENV` 就是原来的行为。

## 3. 不做（本轮明确不碰）

- 不改认证与限流算法（r23/r70 的既有口径一律保留）；
- 不引入 CDN / WAF / 对象存储 / Postgres（单副本形态不变，写在已知边界里）；
- 不做自动扩缩容与多副本（SQLite 单写，先换存储再谈水平扩展）；
- 不开放注册（账号仍由 `admin_cli` 创建）；
- 不做证书自动轮换的守护进程（用 cron 调 `cert.sh renew`）。

## 4. 验收口径

| 编号 | 场景 | 期望 |
|---|---|---|
| AC-1 | `APP_ENV=production` 且 `COOKIE_SECURE=false` | 后端**拒绝启动**，日志点名 `COOKIE_SECURE` |
| AC-2 | 生产档 `CORS_ORIGINS=*` 或为空 | 拒绝启动，说明原因 |
| AC-3 | 生产档但关了限流/熔断、`SECRET_KEY` 为空、AI 未配 | 只 WARNING，不阻断（容器要能起、/health 如实报） |
| AC-4 | 不设 `APP_ENV`（本地/CI） | 校验恒空，行为与 r96 完全一致 |
| AC-5 | 生产档访问 `/docs`、`/openapi.json` | 404；开发档仍为 200 |
| AC-6 | http 访问 | 301 到 https，ACME 路径除外 |
| AC-7 | https 响应 | 带 HSTS / nosniff / Referrer / Frame / Permissions / CSP，含 `/api/`、`/health`、`/assets/` |
| AC-8 | `scripts/cert.sh init` / `renew` | init 签发并落 `certs/*.pem`；renew 走 webroot 不停服并 reload |
| AC-9 | `scripts/backup_db.sh` | 在线备份成功、`PRAGMA quick_check = ok`、本地滚动保留 |
| AC-10 | 生产编排 | `-f docker-compose.yml -f docker-compose.prod.yml` 合并后 80/443 对外、8080 仅回环 |
