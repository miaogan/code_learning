#!/usr/bin/env bash
# 本地发版准备：校验准入条件，生成 annotated tag 与 release/vX.Y.Z 分支。
#
# 用法：
#   SKILLCOACH_DEPLOY_SHA=<服务器 deploy-state 里的 40 位 SHA> \
#     bash scripts/release-start.sh v0.2.0
#
# 只做本地对象，不自动 push —— 留出人工确认窗口。脚本会打印后续两条推送命令与 PR 链接。
# 准入清单与完整流程见 docs/teamflow/20261114-cicd/RELEASE.md。
set -euo pipefail

fail() {
    printf 'release-start: FAIL %s\n' "$*" >&2
    exit 1
}
ok() { printf 'release-start: OK   %s\n' "$*"; }

VER="${1:-}"
[[ "$VER" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
    fail "用法：bash scripts/release-start.sh v0.2.0（版本号形如 v0.2.0）"

cd "$(dirname "$0")/.."

# 1. 只能在 dev 上、且工作树干净时发版。
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "dev" ] || fail "当前分支是 $BRANCH；发版必须在 dev 上执行"
[ -z "$(git status --porcelain)" ] || fail "工作树不干净，先提交或 stash"
ok "在 dev 上，工作树干净"

git fetch --quiet origin dev
HEAD="$(git rev-parse HEAD)"
REMOTE_DEV="$(git rev-parse refs/remotes/origin/dev)"
[ "$HEAD" = "$REMOTE_DEV" ] ||
    fail "本地 HEAD ${HEAD:0:12} 与 origin/dev ${REMOTE_DEV:0:12} 不一致，先 pull --ff-only 或 push"
ok "与 origin/dev 同步：${HEAD:0:12}"

# 2. 最容易被忽略的准入项：CI 绿不等于部署过，tag 必须打在「生产实际运行」的 SHA 上。
#    取法：ssh <运维 key> cyz@43.166.23.144 'cat ~/skillcoach/logs/deploy-state'
#    或用 logs/teamflow/ip-deploy/cd_status.py 交叉确认 deploy-state 落在 deploy job 窗口内。
DEPLOYED="${SKILLCOACH_DEPLOY_SHA:-}"
[[ "$DEPLOYED" =~ ^[0-9a-f]{40}$ ]] ||
    fail "请用 SKILLCOACH_DEPLOY_SHA=<40 位 sha> 传入服务器 logs/deploy-state 里的 SHA（见 RELEASE.md §3）"
[ "$DEPLOYED" = "$HEAD" ] ||
    fail "生产部署的是 ${DEPLOYED:0:12}，当前 dev HEAD 是 ${HEAD:0:12}；等部署完成 / 复验 44 项后再发版"
ok "dev HEAD 已部署到生产：${HEAD:0:12}"

# 3. 变更记录条目必须已写好并随本次发版一起部署。
[ -f CHANGELOG.md ] || fail "缺少 CHANGELOG.md"
grep -qF "## [$VER]" CHANGELOG.md || fail "CHANGELOG.md 缺少 '## [$VER]' 条目，先补写、提交、推送并等部署完成"
ok "CHANGELOG.md 含 ## [$VER]"

# 4. tag 与临时分支都不能与已有对象冲突。
git fetch --quiet --tags --force origin || true
git rev-parse -q --verify "refs/tags/$VER" >/dev/null && fail "本地已存在 tag $VER"
[ -z "$(git ls-remote --tags origin "refs/tags/$VER")" ] || fail "远端已存在 tag $VER；版本号不可复用"
RELEASE_BRANCH="release/$VER"
git rev-parse -q --verify "refs/heads/$RELEASE_BRANCH" >/dev/null && fail "本地已存在 $RELEASE_BRANCH"
[ -z "$(git ls-remote --heads origin "refs/heads/$RELEASE_BRANCH")" ] || fail "远端已存在 $RELEASE_BRANCH"
ok "$VER / $RELEASE_BRANCH 均未被占用"

# 5. 版本号只增不复用。
mapfile -t TAGS < <(git tag --list --sort=-v:refname 'v*')
HIGHEST=""
for t in "${TAGS[@]}"; do
    if [ "$t" != "$VER" ]; then
        HIGHEST="$t"
        break
    fi
done
if [ -n "$HIGHEST" ]; then
    NEWEST="$(printf '%s\n%s\n' "$HIGHEST" "$VER" | sort -V | tail -n 1)"
    [ "$NEWEST" = "$VER" ] || fail "新版本 $VER 不大于已有最高版本 $HIGHEST"
    ok "版本号递增：$HIGHEST -> $VER"
else
    ok "首个版本 $VER"
fi

# 6. 生成对象（不 push）。
git tag -a "$VER" -m "release: $VER" "$HEAD"
git branch "$RELEASE_BRANCH" "$HEAD"
ok "已创建 annotated tag $VER 与分支 $RELEASE_BRANCH（均未推送）"

cat <<EOF

下一步（按顺序）：
  git push origin $VER
  git push origin $RELEASE_BRANCH

  开 PR：$RELEASE_BRANCH -> master，标题写「release: $VER」
  https://github.com/miaogan/code_learning/compare/master...$RELEASE_BRANCH

  等 Release gate / frontend / backend 三项全绿，用 Create a merge commit 合并（不要 squash/rebase）。
  合并后：git push origin --delete $RELEASE_BRANCH && git fetch origin --prune
EOF
