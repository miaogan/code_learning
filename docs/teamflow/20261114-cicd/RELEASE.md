# 版本发布与 master 合入规则

> 生效：2026-11-14 · 仓库 `miaogan/code_learning`（SkillCoach）
> 只回答一个问题：**什么条件下、以什么形式，代码才允许进入 `master`。**

## 1. 分支职责

| 分支 | 谁在写 | 会不会部署 | 生命周期 |
|---|---|---|---|
| `dev` | 日常开发，**唯一写入口** | **会**：每次 push 经 CI 双门禁后自动部署生产 | 长期 |
| `release/vX.Y.Z` | 无人手写，由发版脚本从已验收的 dev commit 切出 | 不会 | 临时，PR 合并后删除 |
| `master` | **只接收 release PR**，不直接提交 | 不会 | 长期，受保护 |

**关键约定：生产实际运行的是 `dev` 的 HEAD，不是 `master`。** `master` 是「已验收版本的存档主干」，
回答「哪些代码曾作为正式版本上线过」，不回答「现在线上跑什么」。线上版本以服务器
`~/skillcoach/logs/deploy-state` 的 SHA 为准，两者由 tag 关联。

稳态下远端只有 `master` 与 `dev` 两条分支；`release/*` 只在发版窗口存在，合并后立即删。

## 2. 版本号

`v0.MINOR.PATCH`（当前处于 0.x，允许不兼容变更）

- `MINOR` +1：可展示的新能力 / 架构级变更（BYOK 预设、CD 链路、滚动更新……），`PATCH` 归零。
- `PATCH` +1：缺陷修复、安全加固、运维与文档改动——**这些同样会部署，所以同样要发版**。
- 预发版本形如 `v0.2.0-rc.1`，本期不启用。
- 只增不减、不复用；`Release gate` 会校验新版本号严格大于已有最高 tag。
- 三个落点必须一致：tag 名、`CHANGELOG.md` 的 `## [vX.Y.Z]` 标题、PR 标题。

> `/health` 的 `version` 字段来自 `backend/app/main.py` 的 `APP_VERSION`，暂不与发布 tag 联动，见 §8。

## 3. 准入清单（缺一不可）

打 tag 之前逐项确认：

1. `dev` 最新 CI run 的 `frontend` / `backend` 双门禁全绿。
2. **该 SHA 确实部署成功**：服务器 `logs/deploy-state` 的 SHA == 待发版 SHA，且时间戳落在对应 deploy job 窗口内。用 `python logs/teamflow/ip-deploy/cd_status.py` 得 `[OK]`。
3. 公网验收 **44/44**（`verify_public.py`，需注入 `SKILLCOACH_DEMO_EMAIL` / `SKILLCOACH_DEMO_PASSWORD`）。
4. 生产稳定观察：至少一次真实使用，或距上次部署 ≥ 24h，期间无 5xx、无容器重启。
5. `CHANGELOG.md` 已写好该版本条目（新增 / 修复 / 运维与安全 / 文档 / 验收）。
6. 证书有效、备份 cron 正常、四容器 healthy。

第 2 条最容易被忽略：**CI 绿 ≠ 部署过**。deploy job 有「Secrets 未配置就 `exit 0`」的跳过守卫；
反过来纯文档改动命中构建缓存时，一次真部署也只要 5 秒，不能用 job 时长判断。

## 4. 发版操作

```bash
# 0) 在 dev 上与远端同步，确认工作树干净
git switch dev && git pull --ff-only
git status --short                       # 必须为空

# 1) 按 §3 验收，把 CHANGELOG.md 该版本条目提交并推送
#    （这一步本身触发一次 dev 部署，等部署完成、44/44 复验通过后再继续）

# 2) 取回服务器实际部署的 SHA，本地预检并生成 tag + release 分支
DEPLOYED=$(ssh <运维 key> cyz@43.166.23.144 'cat ~/skillcoach/logs/deploy-state' | awk '{print $2}')
SKILLCOACH_DEPLOY_SHA="$DEPLOYED" bash scripts/release-start.sh v0.2.0

# 3) 按脚本输出推送（脚本不自动推，留出人工确认窗口）
git push origin v0.2.0
git push origin release/v0.2.0

# 4) 开 PR：release/vX.Y.Z -> master，标题必须写 release: vX.Y.Z
#    网页：https://github.com/miaogan/code_learning/compare/master...release/vX.Y.Z
#    或走 API（本机内置浏览器访问 github.com 可能 ERR_CONNECTION_RESET，但 curl 通；
#    凭据不必另要，git credential fill 就能取到，注意只放变量里、不要打印）：
#    curl -s -X POST -u "$U:$P" -H "Accept: application/vnd.github+json" \
#      --data-binary @payload.json https://api.github.com/repos/miaogan/code_learning/pulls

# 5) 等 Release gate / frontend / backend 三项全绿，用 merge commit 合并（见 §5；
#    单人仓库的 approval 处理见 §5.1）

# 6) 合并后清理临时分支（tag 保留，不要删）
git push origin --delete release/v0.2.0
git fetch origin --prune
```

发版窗口内（`release/*` 存在到 PR 合并）不要往 `dev` 追加属于该版本的改动：`release/*` 的 head
被 tag 钉死，dev 后续 push 不会污染这个批次。若发现必须修，关掉 PR、删临时分支与本地 tag，
修完重走流程并换一个 `PATCH` 号；**已公布的 tag 不删**，用下一个版本修正。

## 5. 为什么必须用 merge commit

tag 打在 `dev` 的某个 commit 上。用 **Create a merge commit** 合并，该 commit 成为 `master` 历史的祖先：

```bash
git describe --tags        # 在 master 上能拿到最近的版本号
git tag --contains <sha>   # 能反查某段代码属于哪个版本
```

Squash / Rebase 会生成全新 SHA，tag 就只挂在 `dev` 上、不在 `master` 历史里，`master` 退化成一串
与版本对不上的快照。因此保护规则里要保留 **Allow merge commits**。

### 5.1 单人仓库：approval 无法自我满足时的标准动作

**问题**：`master` 要求 1 个 approval 且 `enforce_admins=true`，而仓库唯一协作者就是发版人本人；
GitHub 不允许作者批准自己的 PR → **每次发版都会卡在 `blocked`**。v0.4.0 是第一次真实撞上
（v0.1.0 / v0.2.0 当时只在 `dev` 上打了 tag，master 从未接收过 PR）。

发生这种情况时，按下面顺序处理，**不得省略任何一步**：

1. **先等三项必需检查全绿**（`frontend` / `backend` / `Release gate`）。approval 的调整不能替代检查，
   检查没绿就没资格谈合并。
2. **只改一个字段**：`required_approving_review_count` 由 `1` 改为 `0`。
   `dismiss_stale_reviews` / `require_code_owner_reviews` / `contexts` / `strict` / `enforce_admins`
   一律保持原值——**不允许关 `enforce_admins`、不允许减必需检查、不允许长期置 0**。
3. 立即以 **merge commit** 合并（§5），不用 squash / rebase。
4. **恢复放在 `finally` 里**，与合并同一个脚本：合并成功、失败、超时都必须先恢复 `1` 再做别的。
   恢复后重新 `GET /branches/master/protection`，与合并前的快照**逐字段比对**，不一致即视为发版事故。
5. 留档三件：`protection-before.json`、`protection-after.json`、`STEPS.md`（含每步时间戳）。
   v0.4.0 的实例见 `logs/teamflow/r113-release-v040/`。

**长期方案**（二选一，任选其一后本节可退役）：加第二个协作者（人工或发版专用 bot 账号）来审批；
或把发版改成「由 CI 在检查全绿后自动合并」的机器人流程。

> 判断口径：这一步放宽的是**人工复核**，不是**代码门禁**。三项检查一条都不能少，
> 也不能用它给「检查没绿」找台阶。

## 6. CI 门禁：Release gate

`.github/workflows/ci.yml` 的 `release-gate` job 只在 `base = master` 的 PR 上跑，校验：

| # | 校验项 |
|---|---|
| 1 | 来源分支形如 `release/vX.Y.Z`（不允许 `dev` 或其它分支直接合 master） |
| 2 | PR 标题含同一版本号 |
| 3 | `CHANGELOG.md` 存在 `## [vX.Y.Z]` |
| 4 | tag `vX.Y.Z` 存在且是 **annotated tag**（含发版者与日期） |
| 5 | tag 精确指向 PR head SHA —— 合入的必须就是已验收的那个 commit |
| 6 | tag 所在 commit 在 `origin/dev` 历史上 |
| 7 | 新版本号严格大于已有最高 tag |

**需要一次网页配置才真正生效**：Settings → Branches → `master` 保护规则 →
*Require status checks to pass* 里把 `Release gate` 加进必需检查（与 `frontend` / `backend` 并列）。
不加的话这个 job 只是提示、拦不住合并。同时确认已勾选 *Require a pull request before merging*、
*Do not allow bypassing the above settings*，并保留 *Allow merge commits*。

`deploy` job 的 `if` 是 `github.event_name == 'push' && github.ref == 'refs/heads/dev'`，
所以发版 PR **不会触发生产部署**，master 合并也不会——开发和部署始终只在 `dev`。

## 7. 版本表

| 版本 | 日期 | 内容 | 生产 SHA |
|---|---|---|---|
| `v0.1.0` | 2026-11-14 | 首个受控发布基线：BYOK 预设、CD 链路、IP 证书、r99 加固、版本发布流程 | `b5d92ff` |
| `v0.2.0` | 2026-11-16 | 第二批发版（仅在 `dev` 打 tag，**master 未接收**，见 §5.1 背景） | `1e6a627` |
| `v0.4.0` | 2026-11-17 | 岗位闭环：跃迁档案 `/leap`、JD 对位 `/jd`、缺口驱动追问、报告回收缺口、移动端 chip 修复；**首次真正合入 master**（PR #24 → merge commit `4f1e92e`） | `2a74fdf` |
| `v0.3.0` | 未打 tag | 运行时降级兜底（PG → SQLite 副本接管、Redis → 进程内缓存），曾部署 `a170913`，按用户决定暂不补 tag | — |

## 8. 回滚与已知债

- **撤销尚未合并的发版**：关 PR + `git push origin --delete release/vX.Y.Z` + `git tag -d vX.Y.Z`；
  若 tag 已推送，用 `git push origin :refs/tags/vX.Y.Z`。已对外公布的 tag 不删，改用下一个 PATCH 号。
- **生产回滚与版本无关**：走 CD 自带失败回滚（`scripts/deploy-from-ci.sh` 回到上一个 SHA 并复核
  `/health`），或以受限 deploy key 手工 `deploy <旧 SHA>`。`master` 不参与生产回滚。
- **已知债**：`/health` 的 `version` 来自 `backend/app/main.py` 的 `APP_VERSION`（硬编码），
  **每次发版要手工改**，尚未与 tag 联动（v0.4.0 已手工对齐为 `0.4.0`，`/health` 实测一致）。
  要让它自动跟随，需在流程里补「从 tag 写版本」的步骤并加门禁；目前不作发版阻塞项，
  但漏改会出现「tag 是 vX.Y.Z、接口自报旧版本」的口径分裂。
