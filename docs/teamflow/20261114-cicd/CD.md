# 公网服务器自动 CI/CD 落地说明

- **日期**：2026-11-14
- **目标**：`https://43.166.23.144`（纯 IP 生产档，四容器 compose）
- **选型**：GitHub Actions 门禁 + **Actions 推 SSH 触发部署**（用户在候选中选定）

## 1. 为什么是这样

| 已具备 | 实测 |
|---|---|
| 代码托管 | GitHub `miaogan/code_learning`，**public**；`master` 为受保护默认主干、`dev` 为唯一自动部署分支（原 `feat/dev-skill-coach`，2026-11-14 整理） |
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
2. 把 `~/skillcoach` 无损转成 git 工作树：`git init` → `git remote add origin https://github.com/miaogan/code_learning.git` → `git fetch --depth=50 origin dev` → `git checkout -f -B dev FETCH_HEAD`。`checkout -f` 只覆盖被跟踪文件，`deploy.env` / `backend/.env` / `certs/` / `backups/` / `logs/` 全部保留。
3. 公钥追加到 `~/.ssh/authorized_keys`，前缀 `restrict,command="/home/cyz/skillcoach/scripts/deploy-from-ci.sh"`，权限保持 600。
4. `chmod +x scripts/deploy-from-ci.sh`；确认 `logs/` 700、`deploy.env` 与 `backend/.env` 600。
5. 手工冒烟：`ssh ... "deploy <当前 HEAD sha>"`，正常应打印「已是目标版本，跳过」；再改一个无害文件跑真实演练，验证回滚链路。

## 5. 部署脚本的护栏（`scripts/deploy-from-ci.sh`）

| 护栏 | 实现 |
|---|---|
| 命令形状 | 只接受 `deploy <40 位小写 hex>`，从 `SSH_ORIGINAL_COMMAND` 解析 |
| SHA 边界 | 必须存在于对象库，且在 `origin/dev` 最近 50 次提交内 |
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
- **B 组（首轮暂缓，验证后已上线）**：`frontend/src/pages/SettingsPage.tsx` 的改动与新增 `frontend/src/lib/aiProviders.ts`、`frontend/src/test/aiProviders.test.ts`（BYOK 国内厂商预设）。首轮为避免把未随验收的新功能混进 CD 首演而暂缓；随后补齐本地门禁并核对 `docs/teamflow/memory.md` 的 BYOK 约定登记，确认是已落定的产品约定后，按同一条 CD 链路提交部署。**事后看这个暂缓偏保守**：判断依据应是门禁结果，不是「服务器上没出现过」。详见 §9。

## 7. 排障

- CI deploy job 红但服务正常：看 `~/skillcoach/logs/deploy.log`；常见原因是 fetch 失败、备份失败、或 SHA 不在最近 50 次提交内。
- 部署后服务异常：脚本会自动回滚；确认 `docker compose ... ps` 与 `logs/deploy-state`。
- 证书/备份 cron 丢失：不该发生（cron 在用户 crontab，文件在 ignored 目录），用 `crontab -l` 核对两条。
- 想临时停自动部署：`touch ~/skillcoach/deploy.freeze`；恢复用 `rm`（这是服务器侧运维文件，不是危险删除）。

## 8. 仍保留的风险

- `cyz` 在 docker 组 ≡ root（架构性，与本方案无关，仍未根治）。
- 22 端口公网开放；已禁用口令登录，但建议后续评估 fail2ban 与 `PermitRootLogin no`。
- 部署会短暂重建容器（秒级），不是严格零停机；要做零停机需引入双副本 + 负载均衡，当前单 worker 架构不支持。

## 9. 落地与演练记录（2026-11-14）

**已完成的准备**

- 本地提交并推送 5 个 commit：`2e85503`（同步 r99 生产修复 + CD 链路）→ `7ae7f9c`（脚本可执行位）→ `a35ca16`（忽略 logs/ 与上传包）→ `3cbbe9f`（fetch 重试）→ `a975a59`（SHA 校验修正）。
- B 组前端 BYOK 预设 3 个文件首轮暂缓；**随后已验证并上线**（见下方「B 组上线」）。
- 服务器全量备份 `~/skillcoach-backup-20261114-171139.tgz`（600、6.0 MB、766 项，含 `certs/privkey.pem`）。普通 `tar` 会因 certbot 以 root 创建的证书文件报权限拒绝，改用 `docker run -v /home/cyz:/home/cyz alpine` 以容器内 root 打包后 `chown` 回 cyz。
- `~/skillcoach` 已迁成 git 工作树，`checkout -f` 未触碰任何 ignored 运行时文件；证书、cron、600 权限配置全部保留。
- 受限 key 实测：传 `id; cat /etc/passwd` 被脚本拒绝（`RC=1`），拿不到 shell；传合法形状的 SHA 也被按规则拒绝。

**真实部署演练**：用受限 key 手工发 `deploy a975a596...`（等价于 Actions 会发的命令），`DEPLOY_RC=0`：

```
17:18:15 fetch → 17:18:15 DB 备份 → 17:18:16 checkout
17:18:16 构建镜像（86s，旧容器照常服务）
17:19:42 一次性切换 → 17:19:49 健康检查 → 17:19:52 完成
7ae7f9c -> a975a596
```

部署后服务器侧 44/44、国内客户端直连 44/44，`logs/deploy.log` 与 `deploy-state` 均 600，四容器 healthy，证书与两条 cron 完好。

**过程中修掉的两个真 bug**（都不是配置问题，是脚本逻辑问题）：

1. `git rev-list -n 50 FETCH_HEAD | grep -qx "$SHA"` 在 `set -o pipefail` 下：grep 命中即退出，上游 `git rev-list` 吃 SIGPIPE 返回 141，整条管道被判失败，**把合法 SHA 误拒**。服务器实测 `OLD_PIPE_RC=141` 复现。改成 `git merge-base --is-ancestor "$SHA" FETCH_HEAD`（无管道，合法 SHA 返回 0、不存在返回 128）。
2. `chmod +x scripts/*.sh` 在原有 664 上只补 x 得到 **775（group 可写）**，部署脚本可被同组用户改写。改为每次 checkout 后 `chmod 755 scripts/*.sh` 统一收敛。

另外 `git add` 在 Windows 上把 shell 脚本记成 `100644`，迁移后 `checkout -f` 会重置 x bit，导致证书/备份 cron 与受限 key 全部失效；已用 `git update-index --chmod=+x scripts/*.sh` 修为 `100755`。

**Secrets 已于 2026-11-14 18:13 由用户配置完成**：`DEPLOY_SSH_KEY` / `DEPLOY_HOST=43.166.23.144` / `DEPLOY_USER=cyz`。在此之前三次 push 的 deploy job 都是「Secrets 未配置，跳过部署」的**假绿**（run success、job 4 秒、step 0 秒），服务器上跑的是手工 `deploy <sha>` 的结果；配置完成后由一次文档提交触发首次真实自动部署并成功，**验收结果见 §11**。

**专用账号评估结论（同日，已放弃）**：曾评估把 `DEPLOY_USER` 换成零特权账号 `cddeploy`（零特权账号 + 单条精确 sudoers 桥接，脚本在 `logs/teamflow/ip-deploy/setup-cd-user.sh`，**从未执行**）。因部署脚本最终仍须以 `cyz` 身份运行、而 `cyz` 在 `docker` 组 ≡ root，换账号不降低提权上限，也不消除「GitHub Secrets 里放着一把能登录服务器的私钥」这个前提，收益不抵改动成本。用户决定维持 `cyz` + `restrict,command=`，服务器上未执行的脚本已删除。真正根除该风险的是服务器轮询拉模式（§2），留待后续架构变更。

## 10. B 组 BYOK 厂商预设上线（用户质疑后的修正）

用户指出「这个应该在本地验证了」。复核后**撤回暂缓判断**：判断依据应是门禁结果，不是「服务器上没出现过」。

- 代码性质：`frontend/src/lib/aiProviders.ts` 是纯函数填表助手（8 家国内厂商 + 自定义，默认 DeepSeek），`aiProviders.test.ts` 有 9 项单测，`SettingsPage.tsx` 增加服务商下拉、填写提示与状态卡厂商展示；HTTP 契约 `AiSettingsRequest` 四件套与后端零改动。
- `docs/teamflow/memory.md` 已有「BYOK 厂商预设约定（2026-11-14）」登记，是落定的产品约定而非在途草稿，代码中无 TODO / 半成品。
- 本地门禁实测：`npm run typecheck` RC=0、`npm run lint` RC=0、`npm test` **42 文件 / 556 测试全过**、`npm run build` 成功（316 模块，gzip JS 298.86 KiB / CSS 25.68 KiB）。
- 按同一条 CD 链路提交并部署，部署后复验 44 项。

**遗留待拍板（不阻塞上线）**：`docs/teamflow/memory.md` 记录服务端 r9 档 `AI_DEEPSEEK_MODEL` 示例与 `Settings.ai_deepseek_model` 默认值仍是 `deepseek-chat`，而前端预设给 `deepseek-flash`。两者作用域不同（前端预设只填 BYOK 表单且可编辑；服务端默认只影响内置 Key 链路），当前 `AI_DEEPSEEK_API_KEY` 为空，无实际影响。真要统一需产品确认后单独改，不要借 CD 顺手改。

## 11. 首次真实自动部署验收（2026-11-14 18:18）

纯文档提交 `27d25be` 触发，三个 Secrets 首次生效：

| 项 | 实测 |
|---|---|
| run `#43584451758` | success；`frontend` 36s / `backend` 156s / `Deploy to public IP server` 8s |
| `Deploy over SSH` step | `10:18:46Z → 10:18:51Z`（5 秒） |
| 服务器 `logs/deploy-state` | `2026-11-14T18:18:51+08:00 27d25be2…`，恰好是 step 结束时刻 |
| 服务器 `git rev-parse HEAD` | `27d25be2…`（从 `bc9dd77` 推进） |
| `logs/deploy.log` | 第 4 条「完成：bc9dd770… -> 27d25be2…」，含备份 / checkout / build / 切换 / 健康检查 |
| 公网 | `/health` 200、`/docs` 404、TLS 1.3、证书 SAN 正确、四容器 healthy |

**8 秒不是跳过**：这次只改文档，Docker 构建全命中缓存（`deploy.log` 里全是 `DONE 0.0s`）。早期把「≥15 / 30 秒」当真部署门槛是错的，曾据此把这次成功误判成假绿；观测脚本已修正为用 `deploy-state` 的 SHA + 时间戳归因。

验收看四处，缺一不可：

| # | 检查 | 通过标准 |
|---|---|---|
| 1 | 服务器 `logs/deploy-state` | **SHA == 本次 push 的 SHA，且时间戳落在 deploy job `started_at ~ completed_at` 窗口内**。这是核心判据：跳过守卫根本不写这个文件 |
| 2 | 服务器 `git rev-parse HEAD` | == 本次 push 的 SHA |
| 3 | `logs/deploy.log` | 出现「完成：PREV -> SHA」的完整链路 |
| 4 | 公网 | `/health` 200、`/docs` 404、证书可信、四容器 healthy |

**不要用 deploy job 时长判断**：缓存命中时真部署只要 5 秒，前端改动时可能 86 秒，时长取决于构建缓存，与「是否部署」无关。

一键交叉比对（本地只读脚本，在 ignored 目录，不触发 CI）：

```bash
python logs/teamflow/ip-deploy/cd_status.py
```

结论必须是 `[OK]` 而不是 `[!!]`；`[!!]` 表示「代码已上线但不是这次 CI 部署的」。

**三个会骗人的绿色信号**：run 级绿勾、Environments / Deployments 的 `success` 标记（由 `environment: production` 自动生成，与服务器无关）、以及跳过守卫本身 `exit 0`。详见 `logs/teamflow/ip-deploy/CD-OBSERVE.md`。

## 12. 分支模型整理（2026-11-14）

用户拍板：`master` = 受保护的默认主干，`dev` = 日常开发 + 唯一自动部署分支；其余分支清空。

| 改动 | 文件 |
|---|---|
| `on.push.branches: [master, dev]`（去掉 `main` 与 `feat/**`，否则改名后 CI 不触发） | `.github/workflows/ci.yml` |
| deploy job 的 `if` 改为 `refs/heads/dev` | 同上 |
| `BRANCH="dev"` | `scripts/deploy-from-ci.sh` |
| CI badge 指向 `master`，分支章节改写 | `README.md` |
| 三个 update 块加 `target-branch: dev`，依赖 PR 不再打到受保护的 `master` | `.github/dependabot.yml` |
| 观测分支改为 `dev` | `logs/teamflow/ip-deploy/cd_status.py`（ignored） |

**迁移顺序（关键：不能让服务器脚本断链）**：服务器 `deploy-from-ci.sh` 的 `BRANCH` 是硬编码的，必须先通过一次部署把新脚本拉下来，之后才能 fetch `dev`。做法是让 `feat/dev-skill-coach` 与新建的 `dev` **指向同一个改造 commit**：先推 `feat`（此时 workflow 已不监听它，不会触发 CI），保证服务器上的旧脚本仍能 fetch 到目标 SHA；再推 `dev` 触发部署，服务器 checkout 新 commit 后脚本即变成 `BRANCH=dev`。顺序颠倒的话，旧脚本 fetch 不到目标 SHA，会被 `sha_on_branch` 拒绝、deploy job 变红。

`master` 从当前生产 HEAD 创建（本地老 `master` 快进 142 个提交），与 `dev` 同起点。默认分支切换与 `master` 保护规则需在 GitHub 网页操作（本机无 admin token）；**GitHub 不允许删除默认分支**，所以必须先把默认分支挪到 `master`，才能删掉 `feat/dev-skill-coach`。

历史 `docs/teamflow/*` 验收文档里的旧分支名是当时的事实记录，保持原样不改写。

## 13. 事故复盘：`umask 077` 让部署把后端打死（2026-11-14 20:05）

**现象**：`dev` 推上 `dc87512 fix(ai): 修复 BYOK 测试连接把有效 Key 误报为无效` 后，自动部署失败并回滚；但回滚后 `backend` 一直 `Restarting (1)`，公网 `/health` 504，前端静态页能开、所有 API 挂。回滚日志却打印了「回滚完成」。

**根因链**（缺一环都不会出事，所以之前 6 次部署全绿）：

1. `deploy-from-ci.sh` 顶层 `umask 077` —— 本意只让 `logs/deploy.log` 与 `deploy-state` 落盘即 600。
2. 前 6 次部署改的都是文档 / 前端 / 脚本，**没有改过 `backend/app/**/*.py`**。`dc87512` 是第一个改 `ai.py` 的部署。
3. `git checkout --detach --force` 会 unlink + recreate 被改动的跟踪文件，新文件继承 `umask 077` → `ai.py` 变 `600`，新目录变 `700`（实测 16 个跟踪文件权限异常）。
4. `backend/Dockerfile` 的 `COPY app/ ./app/` 把 mode 原样带进镜像，而 `USER app`(uid 10001) 是非 root。
5. `import app.main` → `PermissionError: [Errno 13] ... '/app/app/services/ai/ai.py'` → 容器 unhealthy → `depends_on: backend: service_healthy` 让 `up -d` 直接失败。
6. **回滚走同一条裸 checkout 路径**，把 `ai.py` 又写成 600，于是「回滚完成」是假成功，服务起不来。

**修复**（`scripts/deploy-from-ci.sh`）：

- 新增 `checkout_tree()`：checkout 放在 `( umask 022; git checkout ... )` 子 shell 里；随后 `git ls-files -z | xargs -0 -r chmod go+rX` 兜底归一历史遗留的 600/700（只加读/执行、不加写，且只碰跟踪文件，`.env` / `certs` / `logs` / `backups` 不动）；`chmod 755 scripts/*.sh` 收敛脚本。
- 正常部署与**回滚**共用 `checkout_tree`，不再有第二条绕开修复的路径。
- 构建前断言 `find backend/app -type f ! -perm -o+r`，有不可读文件就在 `up` 之前拒绝，不必等 90s 健康检查。
- 回滚后复核 `/health` 20 次，没恢复就明确喊人工介入，不再无条件打印「完成」。
- `backend/tests/test_engineering_gates.py::test_r100_deploy_checkout_must_not_inherit_umask_077` 把上述约束钉进 CI 静态门禁。

**教训**：`umask` 是进程级全局状态，设了「日志保密」就会顺带影响同一脚本里所有新建文件——包括随后要进 Docker 构建上下文的源码。凡是「先 checkout 再 build」的部署脚本，权限必须显式归一，且不能只靠本地门禁：本地文件是 644、服务器 checkout 后变 600，这个差异只在生产出现。
