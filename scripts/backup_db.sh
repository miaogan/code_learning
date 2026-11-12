#!/usr/bin/env sh
# 公网部署：SQLite 数据卷在线备份（r97）
#
#   ./scripts/backup_db.sh              # 备份到 ./backups，本地保留最近 14 份
#   KEEP=30 DEST=/mnt/backup ./scripts/backup_db.sh
#
# 为什么不直接 cp app.db：SQLite 在写入过程中直接复制文件可能拿到「半页」，
# 恢复后大概率报 database disk image is malformed。这里走 sqlite3 的在线备份 API
# （`Connection.backup`），它在事务边界上拷页面，备份出来的库可以直接打开。
#
# 恢复：把备份文件拷回卷里的 /data/app.db（先停后端），再起容器。
# 具体命令见 docs/teamflow/20261112-r97-public-deploy/DEPLOY.md §5。
set -eu

cd "$(dirname "$0")/.."

KEEP="${KEEP:-14}"
DEST="${DEST:-backups}"
COMPOSE="${COMPOSE:-docker compose}"

mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="app-$STAMP.db"

echo "→ 在容器内做在线备份：$NAME"
$COMPOSE exec -T backend python - "$NAME" <<'PY'
import os
import sqlite3
import sys

name = sys.argv[1]
live = os.environ.get("DB_PATH", "/data/app.db")
os.makedirs("/data/backups", exist_ok=True)
target = f"/data/backups/{name}"

src = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
dst = sqlite3.connect(target)
with dst:
    src.backup(dst)
dst.close()
src.close()

# 立刻自检：备份不可用比没有备份更危险（会在恢复当天才发现）。
check = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
result = check.execute("PRAGMA quick_check").fetchone()
check.close()
if not result or result[0] != "ok":
    sys.exit(f"备份自检失败：{result}")
print("自检通过：quick_check = ok")
PY

CID="$($COMPOSE ps -q backend)"
if [ -z "$CID" ]; then
  echo "找不到 backend 容器；备份暂存在卷内 /data/backups/$NAME" >&2
  exit 1
fi

docker cp "$CID:/data/backups/$NAME" "$DEST/$NAME"
echo "→ 已拷出：$DEST/$NAME（$(du -h "$DEST/$NAME" | cut -f1)）"

# 滚动保留：按修改时间留最近 KEEP 份（容器内与宿主各清一次）。
ls -1t "$DEST"/app-*.db 2>/dev/null | tail -n "+$((KEEP + 1))" | while IFS= read -r old; do
  rm -f "$old"
done
docker exec "$CID" sh -c "ls -1t /data/backups/app-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f"

echo "完成。本地保留最近 $KEEP 份。"
