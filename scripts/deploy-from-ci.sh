#!/usr/bin/env bash
# GitHub Actions 推模式 CD · 服务器侧唯一可执行入口。
#
# 由 ~/.ssh/authorized_keys 的 `restrict,command="..."` 强制调用：客户端传什么命令
# 都会被忽略，只有 `deploy <40 位小写 hex sha>` 这一种形状被接受。即便私钥泄露，
# 对方也拿不到 shell、不能转发端口、不能改命令 —— 这是选「Actions 推 SSH」方案后
# 最重要的安全边界（22 端口无法按 GitHub 的 5622 条出口 CIDR 加白名单）。
#
# 流程：校验 SHA → 串行锁 → 部署前 DB 备份 → fetch → checkout → 先 build 再一次性 up
#       → /health + 首页 + /docs 冒烟 → 任一环节失败自动回到上一个 SHA 并重建。
#
# 关键约束：`git checkout --force` 只覆盖**被跟踪**的文件，`.gitignore` 里的运行时文件
# （deploy.env / backend/.env / certs / backups / logs / demo-account.txt）永远不动。
# 因此证书、AI Key、备份与两条 cron 不会因为部署而丢失。
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG="$ROOT/logs/deploy.log"
STATE="$ROOT/logs/deploy-state"
LOCK="$ROOT/logs/deploy.lock.fd"
FREEZE="$ROOT/deploy.freeze"
BRANCH="feat/dev-skill-coach"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env)
COMPOSE_STR="docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env"

mkdir -p "$ROOT/logs"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "另一次部署正在进行，本次跳过" >&2
  exit 0
fi

log() {
  printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG" >&2
}

if [ -e "$FREEZE" ]; then
  log "部署被冻结（存在 $FREEZE），拒绝执行。面试期间可放置此文件禁用自动部署。"
  exit 1
fi

raw="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "$raw" =~ ^deploy[[:space:]]+([0-9a-f]{40})$ ]]; then
  log "拒绝：非法部署命令形状（只接受 deploy <sha>）"
  exit 1
fi
SHA="${BASH_REMATCH[1]}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "拒绝：部署目录不是 git 工作树"
  exit 1
fi

# 实测踩坑：push 刚完成就 fetch，可能「对象已下载但 FETCH_HEAD 仍指向上一版」，
# 于是 SHA 守卫误拒。这里最多重试 3 次（间隔 3s），覆盖 GitHub 的传播窗口。
# 校验目标 commit 属于本分支历史。
# 千万别写成 `git rev-list | grep -q`：grep -q 命中即退出，上游吃 SIGPIPE(141)，
# 在 `set -o pipefail` 下整条管道被判失败，会把合法 SHA 误拒（实测 RC=141）。
sha_on_branch() {
  git cat-file -e "$SHA^{commit}" 2>/dev/null || return 1
  git merge-base --is-ancestor "$SHA" FETCH_HEAD 2>/dev/null
}

# push 刚完成就 fetch 时，远端指针可能短暂滞后；最多重试 3 次覆盖这个窗口。
log "→ fetch origin/$BRANCH（最多 3 次，等远端指针追上）"
fetched=0
for attempt in 1 2 3; do
  if git fetch --quiet --depth=50 origin "$BRANCH" >>"$LOG" 2>&1; then
    fetched=1
  fi
  if sha_on_branch; then
    break
  fi
  if [ "$attempt" -lt 3 ]; then
    log "第 $attempt 次 fetch 后指针尚未追上 $SHA，3s 后重试"
    sleep 3
  fi
done
if [ "$fetched" -ne 1 ]; then
  log "git fetch 失败，部署中止（服务未改动）"
  exit 1
fi
if ! git cat-file -e "$SHA^{commit}" 2>/dev/null; then
  log "目标 commit 不在本地对象库，拒绝部署：$SHA"
  exit 1
fi
if ! sha_on_branch; then
  log "目标 commit 不在 origin/$BRANCH 历史上（已重试 3 次），拒绝部署：$SHA"
  exit 1
fi

PREV_SHA="$(git rev-parse HEAD)"
if [ "$SHA" = "$PREV_SHA" ]; then
  log "已是目标版本 $SHA，跳过"
  exit 0
fi

log "→ 部署前备份数据库"
if ! COMPOSE="$COMPOSE_STR" ./scripts/backup_db.sh >>"$LOG" 2>&1; then
  log "备份失败，部署中止（服务未改动）"
  exit 1
fi

fail_rollback() {
  log "!! 部署失败，回滚到 $PREV_SHA"
  git checkout --detach --force "$PREV_SHA" >>"$LOG" 2>&1 || true
  "${COMPOSE[@]}" build >>"$LOG" 2>&1 || true
  "${COMPOSE[@]}" up -d --no-build >>"$LOG" 2>&1 || true
  log "回滚完成，请检查 logs/deploy.log 与容器状态"
  exit 1
}

log "→ checkout $SHA（ignored 运行时文件不动）"
git checkout --detach --force "$SHA" >>"$LOG" 2>&1 || fail_rollback

# 先 build 再一次性切换：2 核 4G 构建前端约 1.5 分钟，期间旧容器仍在服务。
log "→ 构建镜像（服务不停）"
"${COMPOSE[@]}" build >>"$LOG" 2>&1 || fail_rollback

log "→ 一次性切换容器"
"${COMPOSE[@]}" up -d --no-build >>"$LOG" 2>&1 || fail_rollback

log "→ 健康检查（最多 90s）"
ok=0
for _ in $(seq 1 30); do
  code="$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/health || true)"
  if [ "$code" = "200" ]; then
    ok=1
    break
  fi
  sleep 3
done
if [ "$ok" -ne 1 ]; then
  log "/health 未在 90s 内恢复 200"
  fail_rollback
fi

root_code="$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/ || true)"
docs_code="$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/docs || true)"
if [ "$root_code" != "200" ] || [ "$docs_code" != "404" ]; then
  log "冒烟不通过：root=$root_code docs=$docs_code（生产档应关 /docs）"
  fail_rollback
fi

printf '%s %s\n' "$(date -Is)" "$SHA" >"$STATE"
log "完成：$PREV_SHA -> $SHA"
