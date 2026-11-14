# 公网 443 放行后 · 外部客户端验收报告

- **时间**：2026-11-14 16:30 GMT+8（腾讯云轻量控制台放行 TCP 443 之后）
- **目标**：`https://43.166.23.144`（纯 IP，无域名、无备案、无 DNS）
- **结论**：**通过**。国内客户端可直连访问，浏览器为受信任的 Let's Encrypt IP 地址证书，44 项公网 HTTP 验收全通过，0 失败。可以用于面试展示。

---

## 1. 测试方法与「为什么这次算数」

之前所有 44 项验证都是在服务器本机用 `SKILLCOACH_RESOLVE_TO=127.0.0.1` 把 IP 映射到回环做的（当时 443 未放行）。本次改为**从国内 Windows 客户端走真实公网链路**，且不再设置该变量。

本机网络环境先做了澄清，否则容易得出假结论：

| 项 | 实测 |
|---|---|
| 默认路由 | `0.0.0.0/0 -> 192.168.31.1`（WLAN，ifIndex 17） |
| 活动网卡 | 仅 WLAN 与 WSL 虚拟网卡，先前的 `wandacloud` TUN 已退出 |
| `Test-NetConnection 443 / 22` | `True` / `True` |
| 会话注入的代理 | `HTTPS_PROXY=http://127.0.0.1:50900` |

**关键坑**：本会话注入了 `HTTP_PROXY/HTTPS_PROXY`，默认 curl 会走本地 CONNECT 隧道，此时 `remote_ip=127.0.0.1`、TLS 握手 1.56s。所有下面报告的数字都用 `curl --noproxy '*'` 或 `env -u HTTP_PROXY -u HTTPS_PROXY ...` 取得，确认 `remote_ip=43.166.23.144`。该代理只影响本会话的命令行工具，**不影响面试官自己的浏览器**。

证书校验全程为默认严格模式：未使用 `-k`、`--insecure`，未设置 `SKILLCOACH_INSECURE`。

---

## 2. 结果总览

| 项目 | 结果 | 判据 |
|---|---|---|
| 外部 44 项 HTTP 验收 | **44/44，0 失败** | `EXTERNAL_VERIFY_RC=0`，`PASS=44 FAIL=0` |
| HTTPS 入口 | 200 | `https://43.166.23.144/health`、`/` 均 200 |
| HTTP → HTTPS | 301 | `Location: https://43.166.23.144/`，且 301 也带六项安全头 |
| TLS 证书校验 | 5/5 `verify=0` | Schannel / .NET / Python 三套信任链均通过 |
| TLS 版本 | 1.0、1.1 拒绝；1.2、1.3 可用 | 见 §4 |
| 敏感路径 | 全部 404 | 见 §5 |
| SSRF 防护（公网视角） | 全部拒绝 | 见 §5 |
| 真实浏览器 | 正常渲染 | Edge 打开登录页，无证书拦截页 |
| 四容器 | backend / postgres / redis `healthy`，frontend `Up` | 服务器侧 |

完整逐项日志：`logs/teamflow/ip-deploy/verify-external-443.log`（46 行，44 条 PASS + 表头 + 汇总）。

---

## 3. 性能（直连，5 次采样）

| # | TCP connect | TLS 握手 | 总耗时 | 证书校验 |
|---|---|---|---|---|
| 1 | 0.0533s | 0.1179s | 0.1715s | 0 |
| 2 | 0.0492s | 0.1074s | 0.1565s | 0 |
| 3 | 0.0522s | 0.1146s | 0.1665s | 0 |
| 4 | 0.0478s | 0.1728s | 0.2201s | 0 |
| 5 | 0.0557s | 0.1212s | 0.1780s | 0 |

首尔节点、国内直连约 50ms RTT，首屏不需要加速器。**不要拿走本地代理时的 1.56s TLS 去评估面试官体验**，那是代理开销。

---

## 4. 证书与 TLS

```
issuer    : C=US, O=Let's Encrypt, CN=YE2
subject   : (空，仅 SAN)
SAN       : IP Address:43.166.23.144   [critical]
notBefore : Nov 14 06:33:21 2026 GMT
notAfter  : Nov 20 22:33:20 2026 GMT   (160h / 约 6.7 天)
```

服务端发送完整 4 张证书链：`leaf → YE2 → Root YE → ISRG Root X2`（shortlived profile 的新 PKI 层级，带交叉签名兼容旧客户端）。

**关于 `Verify return code: 20` 的一次误判**：Git Bash 自带 openssl 的 `OPENSSLDIR=/usr/ssl` 下没有 CA 文件，裸跑 `s_client` 才报 `unable to get local issuer certificate`。显式指定 `-CAfile /mingw64/etc/ssl/certs/ca-bundle.crt` 后是 `Verify return code: 0 (ok)`，不是服务端缺链。以下三套独立信任链也都通过：

- curl 8.22.0 编译为 **Windows Schannel**（`libcurl/8.22.0 Schannel`），`ssl_verify_result=0`；
- PowerShell / .NET `Invoke-WebRequest` 返回 200（Windows 系统证书存储）；
- Python `ssl.create_default_context()` 返回 200（44 项验收使用）。

| 协议 | 结果 |
|---|---|
| TLS 1.0 | REJECTED（`Cipher is (NONE)`） |
| TLS 1.1 | REJECTED（`Cipher is (NONE)`） |
| TLS 1.2 | OK，`ECDHE-ECDSA-AES256-GCM-SHA384` |
| TLS 1.3 | OK，`TLS_AES_256_GCM_SHA384` |

补充：按 RFC 6797 §8.1.1，浏览器不会把 IP 字面量记为 Known HSTS Host，所以即便 6 天短证书万一过期，也不会变成「无法点继续」的 HSTS 硬锁。但这不能替代自动续期——服务器已装每 12 小时 `cert-ip.sh renew` + 剩余不足 48h 硬失败守卫，本轮实测 `renew RC=0`、ACME http-01 挑战文件返回 200。

---

## 5. 安全面外部复核

**响应头**（`/` 与 `/health` 均齐）：`Strict-Transport-Security`、`X-Content-Type-Options: nosniff`、`Referrer-Policy`、`X-Frame-Options: DENY`、`Permissions-Policy`、`Content-Security-Policy`；无重复头；`/health` 带 `no-store`；`Server: nginx` 不带版本号。

**敏感路径**（走真实公网 443）：

| 路径 | 状态 |
|---|---|
| `/.env`、`/.git/config`、`/backup.sql` | 404 |
| `/docs`、`/openapi.json` | 404 |
| `/assets/`（列目录） | 403（禁止列目录，属预期） |
| `/`、带哈希的 `assets/*.js` | 200 |

**SSRF 防护**（先登录演示账号，再从公网提交内网地址）：

| 请求 | 结果 |
|---|---|
| `POST /api/me/ai/test` `http://127.0.0.1:1/v1` | 200，`ok=false`，`API 地址不允许指向本机、内网或云元数据地址` |
| 同上 `http://169.254.169.254/latest/meta-data` | 200，`ok=false`，同上拒绝 |
| 同上 `http://10.0.0.5/v1` | 200，`ok=false`，同上拒绝 |
| `PUT /api/me/ai` `http://10.0.0.5/v1` | 422 `VALIDATION_ERROR`，同上拒绝 |

**44 项覆盖范围**：入口 301 / health / 六项安全头 / 无重复头 / no-store / CORS 预检、生产档 docs 关闭、登录成功与 `sc_session` Cookie 的 `Secure` + `HttpOnly` + `SameSite=Lax`、未授权访问拒绝、业务读写通路（eval summary、history、taifu、profiles、reports、题目检索、笔试 405/422 中文 envelope）、刷新后会话仍有效。

---

## 6. 服务器侧配套状态（本轮之前已验证）

- 四容器：backend / postgres / redis `healthy`，frontend `Up`。
- cron 两条（均已改为 `sh -c 'umask 077; ... >> log 2>&1'`，日志天生 600）：
  ```cron
  12 */12 * * * cd /home/cyz/skillcoach && sh -c 'umask 077; exec ./scripts/cert-ip.sh renew >> logs/cert-ip-renew.log 2>&1'
  25 3 * * * cd /home/cyz/skillcoach && sh -c 'umask 077; export COMPOSE="..."; exec ./scripts/backup_db.sh >> logs/backup.log 2>&1'
  ```
- 每日备份 + 恢复演练：`users=1 questions=1284` 与生产一致，临时库已清；所有 dump/log 权限 600，目录 700。
- 本地工程门禁：后端全量 pytest **935 / 0 failures / 0 errors / 1 skipped**，ruff 全绿，SSRF 回归 25/25。

---

## 7. 面试展示建议

1. 直接把 `https://43.166.23.144` 发给对方或共享屏幕打开。**不要**提示面试官装 VPN / 加速器 / 改 hosts——实测国内直连即通，要求对方装工具只会增加失败点。
2. 面试前一天跑一次 `cd ~/skillcoach && ./scripts/cert-ip.sh status`，确认剩余有效期 > 48h；再从本机跑一次 `verify_public.py`。
3. 证书只有 160 小时。若两次面试间隔较长，看一眼 `~/skillcoach/logs/cert-ip-renew.log` 是否有续期失败。
4. 保留兜底：本地录屏 / 共享屏幕本机演示。公网链接是加分项，不应成为唯一路径。
5. 演示账号是 shared Key 模式，填了 AI Key 后每人每天 20 次调用上限，别在现场做高并发演示。

---

## 8. 未完成事项与残留风险

**仍需你本人操作**：

- 收紧 22 端口来源到自己的出口 IP（当前仍 `0.0.0.0/0`）。
- root / WebShell：`apt update && apt upgrade -y`（212 个可升级包）、`PermitRootLogin no`、可选启用 fail2ban。
- 填 `~/skillcoach/backend/.env` 的 `AI_DEEPSEEK_API_KEY` 并重建 backend。当前 `/health` 的 `ai_configured:true` 只表示 base_url/model 完整，**不代表 Key 可用**，AI 功能实际调用会失败。
- 面试结束后撤销 `interview-demo-temp-20261114` 公钥、改掉或禁用演示账号。

**架构性残留风险**：

- `cyz` 在 docker 组仍等价 root；轮换 PG 口令只让会话里那个泄露值失效，`docker inspect` 依然能读 backend 环境变量。根治要移除 docker 组 / 改 rootless Docker / 改 secret 挂载。
- SSRF 的 DNS rebinding 理论绕过：当前是解析后判定公网 IP，尚未把已校验 IP 钉进 httpx 连接层。

**本次未覆盖**：

- 未做多运营商 / 多地域拨测（仅一台国内 WLAN 客户端）。
- 浏览器截图只截页面内容，不含地址栏；但 Edge 正常渲染出登录页、无「连接不是私密连接」拦截页，配合三套系统级证书链校验，绿锁结论成立。
- 未做异地备份。

---

## 9. 复现命令

```bash
# 本机（国内客户端）：清掉会话代理，严格校验证书，跑 44 项
# 演示账号从服务器 600 权限文件读取，不要写进命令行或提交
cd /d/work_space/code_learning
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  -u SKILLCOACH_RESOLVE_TO -u SKILLCOACH_INSECURE \
  python -X utf8 logs/teamflow/ip-deploy/verify_public.py

# 直连延迟与证书校验
curl --noproxy '*' -o /dev/null \
  -w 'code=%{http_code} verify=%{ssl_verify_result} ip=%{remote_ip} total=%{time_total}s\n' \
  https://43.166.23.144/health

# 服务端状态
cd ~/skillcoach && ./scripts/cert-ip.sh status && crontab -l
```
