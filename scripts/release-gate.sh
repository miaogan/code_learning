#!/usr/bin/env bash
# Release gate：PR 合入 master 前的版本门禁。
#
# 由 .github/workflows/ci.yml 的 release-gate job 调用（仅 base=master 的 PR）。
# 它不判断代码质量（那是 frontend / backend 双门禁的事），只判断「这一批代码
# 是否有资格作为一个正式版本进入受保护主干」。
#
# 环境变量（由 workflow 注入）：
#   PR_HEAD_REF  来源分支名，必须形如 release/vX.Y.Z
#   PR_HEAD_SHA  PR head 的 40 位 commit SHA
#   PR_TITLE     PR 标题，必须含同一版本号
set -euo pipefail

fail() {
    printf 'release-gate: FAIL %s\n' "$*" >&2
    exit 1
}
ok() { printf 'release-gate: OK   %s\n' "$*"; }

PR_HEAD_REF="${PR_HEAD_REF:-}"
PR_HEAD_SHA="${PR_HEAD_SHA:-}"
PR_TITLE="${PR_TITLE:-}"

# 1. 来源必须是固定住 head 的临时发版分支。
#    不允许 dev 直接合 master：dev 会持续前进，PR head 一移动，
#    「合入的是已验收的那个 SHA」就不再成立。
[[ "$PR_HEAD_REF" =~ ^release/v[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
    fail "来源分支必须是 release/vX.Y.Z（实际：'${PR_HEAD_REF}'）；不允许 dev 或其它分支直接合 master"
VER="${PR_HEAD_REF#release/}"
ok "来源分支 $PR_HEAD_REF -> 版本 $VER"

# 2. PR 标题声明同一版本，避免「分支叫 v0.2.0、标题随手写」造成追溯断层。
[[ "$PR_TITLE" == *"$VER"* ]] ||
    fail "PR 标题需含版本号 $VER，例如：release: $VER"
ok "PR 标题含 $VER"

# 3. 变更记录必须有该版本条目。
[ -f CHANGELOG.md ] || fail "缺少 CHANGELOG.md"
grep -qF "## [$VER]" CHANGELOG.md || fail "CHANGELOG.md 缺少 '## [$VER]' 条目"
ok "CHANGELOG.md 含 ## [$VER]"

# 4. tag 必须存在，且是 annotated tag（lightweight tag 不含发版者与日期，追溯性弱）。
git rev-parse -q --verify "refs/tags/$VER" >/dev/null ||
    fail "缺少 tag $VER；请先在已部署并验收的 dev commit 上打 annotated tag"
[ "$(git cat-file -t "refs/tags/$VER")" = "tag" ] ||
    fail "$VER 是 lightweight tag；必须用 git tag -a 打 annotated tag"
ok "tag $VER 是 annotated tag"

# 5. tag 必须精确指向 PR head —— 这是「合入 master 的就是线上验收过的那份代码」的硬保证。
TAG_SHA="$(git rev-list -n 1 "$VER")"
[ "$TAG_SHA" = "$PR_HEAD_SHA" ] ||
    fail "tag $VER 指向 $TAG_SHA，但 PR head 是 $PR_HEAD_SHA；发版批次必须固定"
ok "tag 精确指向 PR head ${PR_HEAD_SHA:0:12}"

# 6. 该 commit 必须在 dev 历史上，防止从旁支打 tag 绕过自动部署验收。
git rev-parse -q --verify refs/remotes/origin/dev >/dev/null ||
    fail "CI 未取到 origin/dev 历史（workflow 需 fetch dev）"
git merge-base --is-ancestor "$TAG_SHA" refs/remotes/origin/dev ||
    fail "tag $VER 不在 origin/dev 历史上；只有经 dev 部署过的 commit 才能发版"
ok "tag 在 origin/dev 历史上"

# 7. 版本号只增不复用。不用管道 grep|head（pipefail 下 head 提前退出会吃 SIGPIPE）。
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
    [ "$NEWEST" = "$VER" ] ||
        fail "新版本 $VER 不大于已有最高版本 $HIGHEST；版本号只增不复用"
    ok "版本号递增：$HIGHEST -> $VER"
else
    ok "首个版本 $VER"
fi

printf 'release-gate: PASS %s (%s)\n' "$VER" "${PR_HEAD_SHA:0:12}"
