# 公网自用部署：内网穿透 + Basic Auth（r21）

> 目标形态：后端仍跑在**本机**（数据不出这台机器），用内网穿透把端口暴露到公网，
> 手机只要联网就能访问，**不依赖局域网、不把后端起在云上**。
> 云服务器到位后再迁移，本文末给出迁移清单。

## 1. 链路

```
手机浏览器
  → https://xxxx.trycloudflare.com      (Cloudflare 边缘，自动 HTTPS)
  → cloudflared 隧道 → 本机 localhost:8080
  → nginx 容器：Basic Auth 闸门
      ├─ /            静态托管 frontend/dist（SPA fallback）
      └─ /api/ /health 同源反代 → backend:8000（FastAPI + SQLite 命名卷）
```

同源反代是关键：页面与接口同一个 origin，所以**不需要改 CORS 白名单**
（[config.py](../../../backend/app/config.py) 默认只放行 5173，那是 vite 开发期的事）。

## 2. 本机现状（实测）

| 组件 | 状态 |
| --- | --- |
| Docker CLI | ✅ 29.9.2 |
| Docker daemon | ⚠️ 需先启动 Docker Desktop |
| compose | ✅ **命令是 `docker-compose`（v5.6.1）**；本机没有 `docker compose` 插件形式 |
| cloudflared | ❌ 未安装（`winget install --id Cloudflare.cloudflared -e`） |
| openssl | ✅ 3.5.9（Git Bash 自带，用于生成密码） |

## 3. 步骤

```bash
# 1) 生成公网访问口令（不入库；文件缺失时 compose up 会失败，这是刻意的）
scripts/gen-htpasswd.sh

# 2) 起容器（注意是 docker-compose，不是 docker compose）
docker-compose up -d --build

# 3) 本机自检
curl -u skillcoach:<密码> -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/
curl -u skillcoach:<密码> -s http://localhost:8080/health

# 4) 开隧道（另开一个终端，保持前台运行）
scripts/tunnel.sh
```

终端会打印 `https://xxxx.trycloudflare.com`，手机浏览器打开 → 输入用户名/密码 → 即用。

## 4. 必知的安全事项

1. **Basic Auth 是公网暴露的底线，不要关掉**。`backend/.env` 里有真实 AI Key，
   无鉴权等于把 Key 和简历一起挂在公网上（谁拿到 URL 谁花你的额度）。
2. **必须走 HTTPS**。`navigator.clipboard` 只在 secure context 可用；
   用 `http://` 公网地址时报告页「复制 Markdown」会失败。
   cloudflared 自带 HTTPS，正好满足。
3. **quick tunnel 的 URL 每次重启都会变**，手机书签会失效。要固定就上
   named tunnel（需自有域名），或等云服务器。
4. `/health` 也在鉴权后面，因此**外部探活/监控需要带凭据**；
   容器编排不受影响（backend 的 healthcheck 由容器内部直连 8000）。

## 5. 隧道层的超时约束（为什么现在不做任务化）

Cloudflare 免费隧道的边缘对长响应有约 100s 的限制。当前配置是云端 DeepSeek：

- `AI_TIMEOUT_S=20`、`AI_MAX_RETRIES=1`
- 报告生成最多 2 处 AI 调用（`services/diagnosis.py:475` / `:609`，其中一处 `asyncio.gather` 并行）
- 最坏 ≈ 20s × 2 次重试 × 2 次调用 ≈ 80s < 100s

所以**当前不需要把画像/报告改成异步轮询**。但若切回本地 LM Studio 档
（实测单次画像 201–224s，见 [r9 标定](../../../docs/teamflow/memory.md)），
必然撞边缘超时 —— 那时必须先做 202 + 轮询的任务化，或改用 frp 直连自建 VPS。

nginx 自身已是 `proxy_read_timeout 1300s`（r9 为本地模型留的），不是瓶颈。

## 6. 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `docker: unknown command: docker compose` | 本机是 v1 命令名，用 `docker-compose` |
| compose 报 daemon 连接失败 | 先启动 Docker Desktop |
| 容器起不来、nginx 报 `/etc/nginx/.htpasswd` 是目录 | 忘了跑 `scripts/gen-htpasswd.sh`；docker 把缺失的源创建成了同名空目录。删掉 `frontend/.htpasswd/` 目录后重跑脚本 |
| 改了密码不生效 | `docker-compose up -d --force-recreate frontend` |
| 手机能开页面但复制按钮失败 | 用了 http 地址；换 https 隧道地址 |

## 7. 回滚

- 只想回到局域网/本机访问：停掉 `scripts/tunnel.sh`，关掉 Docker Desktop 之外的暴露途径即可；
- 想彻底去掉鉴权：删除 `frontend/nginx.conf` 里 server 层的两行 `auth_basic*`，
  并删掉 `docker-compose.yml` 的 `.htpasswd` 挂载（**不建议**，除非只在可信网络内使用）。

## 8. 后续迁云服务器（预计 1 人日以内）

该有的都已在：双容器 compose、同源反代、SQLite 落命名卷 `skillcoach-data`
（`docker-compose down` 不丢数据）。迁移只需：

1. 新机器装 Docker + compose，克隆仓库，写 `backend/.env`；
2. 恢复数据卷：备份本机 `skillcoach-data` → 拷到新机同名卷；
3. 换域名 + HTTPS（nginx 或前置反代都行），保留 Basic Auth 或换更正规的鉴权；
4. 手机端不换地址（只换域名），前端零改动。

届时 `scripts/tunnel.sh` 就不再需要。
