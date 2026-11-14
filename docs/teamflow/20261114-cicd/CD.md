# 公网服务器自动 CI/CD 落地说明

- **日期**：2026-11-14
- **目标**：`https://43.166.23.144`（纯 IP 生产档，四容器 compose）
- **选型**：GitHub Actions 门禁 + **Actions 推 SSH 触发部署**（用户在候选中选定）

## 1. 为什么是这样

| 已具备 | 实测 |
|---|---|
| 代码托管 | GitHub `miaogan/code_learning`，**public**，默认分支 `feat/dev-skill-coach`（仓库无 `main`） |
| CI 门禁 | 前端 5 步、后端 8 步，自带 PG16 + Redis 8 services，含 `pip-audit`、题库字节门禁、4 个离线评测门禁 |
| 服务器 | git 2.43；`https://github.com` 返回 200、`ssh.github.com:443` 可达；磁盘可用 49G；已有约 1GB 构建缓存 |
| 权限形态 | 纯用户态（cyz + docker 组 + 用户 crontab），全程不需要 sudo |

链路：`push → 两个门禁 job 全绿 → deploy job 用受限 key SSH 到服务器 → deploy <sha> → 服务器校验 SHA、备份、构建、切换、健康检查、失败回滚`。

## 2. 必须知道的约束（选型代价）

**GitHub Actions 出口 IP 共 5622 条 IPv4 + 2728 条 IPv6 CIDR**（`https://api.github.com/meta` 的 `actions` 字段）。腾讯云轻量安全组不可能逐条加白名单，因此：

- 选「Actions 推 SSH」就意味着 **22 端口保持对公网开放**，与「把 22 收紧到自己出口 IP」的加固计划互斥；
- 安全边界改由 **受限 deploy key** 承担：公钥在 `authorized_keys` 里带 `restrict,command=".../scripts/deploy-from-ci.sh"`，禁用 PTY / 端口转发 / X11，并强制只执行部署脚本；客户端命令只是传一个 SHA，脚本再独立校验 SHA 属于本分支最近 50 次提交；
- workflow 写死服务器 SSH 主机公钥（`StrictHostKeyChecking=yes` + 固定 `known_hosts`），防 CI 出口被中间人劫持；
- 若将来必须收紧 22，只能改成**服务器轮询的拉模式**（CI 全绿后推进 `deployed` 分支指针，服务器 cron 比对 SHA 自行部署），或引入隧道方案。本方案的脚本层已按 SHA 部署设计，切换到拉模式时 `deploy-from-ci.sh` 可复用，只需换触发端。

当前 22 本来就是 `0.0.0.0/0`（收紧一直是待办，尚未执行），所以本次**不需要改安全组**。

## 3. GitHub 侧需要配置的 Secrets

| Secret | 值 |
|---|---|
| `DEPLOY_SSH_KEY` | 专用 ed25519 **私钥全文**（含 `-----BEGIN ... -----` 与结尾换行） |
| `DEPLOY_HOST` | `43.166.23.144` |
| `DEPLOY_USER` | `cyz` |

私钥文件在 `C:\Users\user\.ssh\cd-deploy-key`，**不进仓库、不进对话、不进日志**。Windows 下 Git Bash 的 `chmod` 对 NTFS ACL 不生效，本机直接 `ssh -i` 会被 OpenSSH 以 `Load key ... Permission denied` 拒绝；这不影响 CI（GitHub Actions 在 Linux runner 上会把明文写成 600 文件），本机如需验证可用 `ssh-agent` 从 stdin 加载。填完 Secret 后可删除该文件。

deploy job 带「Secrets 未配置就跳过」守卫，所以可以**先推代码、后填 Secrets**，不会让门禁全绿的 CI 变红。

`ci.yml` 的 `environment: production` 会创建同名 Environment；如需人工把关，可在仓库 Settings → Environments → production 里加 required reviewers。

## 4. 一次性服务器配置

1. 全量备份：`tar czf ~/skillcoach-backup-<ts>.tgz -C ~ skillcoach`（含所有 ignored 运行时文件）。
2. 把 `~/skillcoach` 无损转成 git 工作树：`git init` → `git remote add origin https://github.com/miaogan/code_learning.git` → `git fetch --depth=50 origin feat/dev-skill-coach` → `git checkout -f -B feat/dev-skill-coach FETCH_HEAD`。`checkout -f` 只覆盖被跟踪文件，`deploy.env` / `backend/.env` / `certs/` / `backups/` / `logs/` 全部保留。
3. 公钥追加到 `~/.ssh/authorized_keys`，前缀 `restrict,command="/home/cyz/skillcoach/scripts/deploy-from-ci.sh"`，权限保持 600。
4. `chmod +x scripts/deploy-from-ci.sh`；确认 `logs/` 700、`deploy.env` 与 `backend/.env` 600。
5. 手工冒烟：`ssh ... "deploy <当前 HEAD sha>"`，正常应打印「已是目标版本，跳过」；再改一个无害文件跑真实演练，验证回滚链路。

## 5. 部署脚本的护栏（`scripts/deploy-from-ci.sh`）

| 护栏 | 实现 |
|---|---|
| 命令形状 | 只接受 `deploy <40 位小写 hex>`，从 `SSH_ORIGINAL_COMMAND` 解析 |
| SHA 边界 | 必须存在于对象库，且在 `origin/feat/dev-skill-coach` 最近 50 次提交内 |
| 并发 | `flock -n`，重叠部署直接跳过而不是互相踩 |
| 冻结窗口 | 存在 `~/skillcoach/deploy.freeze` 时拒绝部署（面试期间用） |
| 数据安全 | 切换前跑 `scripts/backup_db.sh`，备份失败即中止，服务不动 |
| 缩短中断 | 先 `docker compose build`（旧容器照常服务），再一次性 `up -d --no-build` |
| 健康检查 | `/health` 轮询最多 90s；再验 `/` 200、`/docs` 404（确认生产档） |
| 失败回滚 | checkout 回 `PREV_SHA` → 重建镜像 → 重新 up，日志留痕 |
| 权限 | `umask 077`，`logs/deploy.log` 天生 600；状态写 `logs/deploy-state` |
| 运行时文件 | `git checkout -f` 不触碰 `.gitignore` 里的 `.env` / 证书 / 备份 / cron 配置 |

**2 核 4G 前端构建约 1.5 分钟 CPU 打满**，面试当天务必创建 `deploy.freeze` 冻结自动部署。

## 6. 代码提交分组（避免生产回退 / 误上新功能）

落地前发现本地工作树有 26 个改动、远端 HEAD 与本地 HEAD 相同，但服务器跑的是含 r99 修复的 tar 包。分组原则：

- **A 组（必须推）**：r99 SSRF 修复、IP 证书脚本、nginx 规则、CI 版本对齐、compose/env 示例、备份脚本、验收报告，以及本次新增的 CD 文件。这些服务器已在跑，不推就会在第一次自动部署时被 checkout 回旧版。
- **B 组（本次不推）**：`frontend/src/pages/SettingsPage.tsx` 的改动与新增 `frontend/src/lib/aiProviders.ts`、`frontend/src/test/aiProviders.test.ts`（BYOK 国内厂商预设）。服务器上 `SettingsPage.tsx` 的 `aiProviders` 引用数为 0，证实是**尚未部署、未随本次验收的新功能**。保持本地未提交，等单独验证后再走一次 CD。

## 7. 排障

- CI deploy job 红但服务正常：看 `~/skillcoach/logs/deploy.log`；常见原因是 fetch 失败、备份失败、或 SHA 不在最近 50 次提交内。
- 部署后服务异常：脚本会自动回滚；确认 `docker compose ... ps` 与 `logs/deploy-state`。
- 证书/备份 cron 丢失：不该发生（cron 在用户 crontab，文件在 ignored 目录），用 `crontab -l` 核对两条。
- 想临时停自动部署：`touch ~/skillcoach/deploy.freeze`；恢复用 `rm`（这是服务器侧运维文件，不是危险删除）。

## 8. 仍保留的风险

- `cyz` 在 docker 组 ≡ root（架构性，与本方案无关，仍未根治）。
- 22 端口公网开放；已禁用口令登录，但建议后续评估 fail2ban 与 `PermitRootLogin no`。
- 部署会短暂重建容器（秒级），不是严格零停机；要做零停机需引入双副本 + 负载均衡，当前单 worker 架构不支持。
