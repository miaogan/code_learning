#!/usr/bin/env sh
# 公网部署：PostgreSQL 逻辑备份（r98，替换 r97 的 SQLite 在线备份）
#
#   ./scripts/backup_db.sh                       # 备份到 ./backups，本地保留最近 14 份
#   KEEP=30 DEST=/mnt/backup ./scripts/backup_db.sh
#   BACKUP_FORMAT=plain ./scripts/backup_db.sh   # 输出可读 .sql（默认 custom，可选择性恢复）
#
# 为什么用 pg_dump 而不是 cp 数据目录：PG 的数据目录在运行中直接拷贝**一定**是坏备份
# （页面与 WAL 不一致）。pg_dump 走 MVCC 快照，导出的是一致性逻辑备份；`-Fc` 格式还支持
# `pg_restore --table=...` 只恢复一张表，排障时不用整库回滚。
#
# 恢复（先停后端，避免连接占用）：
#   docker compose stop backend
#   docker compose exec -T postgres pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists < backups/app-xxx.dump
# 具体命令见 docs/teamflow/20261112-r98-redis-pg/DEPLOY.md §6。
set -eu

# 备份里是完整的用户表（含口令哈希、加密后的 AI Key），默认 umask 022/002 会写出
# 664/644 让同机其他账号可读。脚本一开头就收紧，保证 dump 从创建那一刻起就是 600。
umask 077

cd "$(dirname "$0")/.."

KEEP="${KEEP:-14}"
DEST="${DEST:-backups}"
COMPOSE="${COMPOSE:-docker compose}"
FORMAT="${BACKUP_FORMAT:-custom}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-sc_app}"

mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"

case "$FORMAT" in
  plain)
    NAME="app-$STAMP.sql"
    DUMP_FLAGS="-Fp --no-owner --no-privileges"
    ;;
  custom|*)
    NAME="app-$STAMP.dump"
    DUMP_FLAGS="-Fc --no-owner --no-privileges"
    ;;
esac

echo "→ pg_dump：$NAME（库 $DB_NAME，用户 $DB_USER）"

# `-T` 关掉 TTY 分配：pg_dump 的 custom 格式是二进制，不能经终端转码。
# 输出直接重定向到宿主文件，不落容器内临时目录（省一次 docker cp，也少一份残留）。
$COMPOSE exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" $DUMP_FLAGS > "$DEST/$NAME"

if [ ! -s "$DEST/$NAME" ]; then
  echo "备份文件为空：pg_dump 失败（看上面 stderr）" >&2
  rm -f "$DEST/$NAME"
  exit 1
fi

echo "→ 已写出：$DEST/$NAME（$(du -h "$DEST/$NAME" | cut -f1)）"

# 立刻自检：备份不可用比没有备份更危险（会在恢复当天才发现）。
# plain 格式用 `psql -f /dev/null` 无法校验语法，这里只对 custom 格式做 `pg_restore -l`。
# 从 stdin 读归档时**不要写 `-`**：pg_restore 会把位置参数 `-` 当成文件名
# （PG16 实测报 `could not open input file "-"`），省略位置参数才是「读 stdin」。
# 少了这个自检曾让每次备份都误报失败、cron 天天红，而 .dump 其实是完好的。
if [ "$FORMAT" != "plain" ]; then
  if $COMPOSE exec -T postgres pg_restore -l < "$DEST/$NAME" > /dev/null 2>&1; then
    echo "→ 自检通过：pg_restore -l 能读出目录（归档结构完整）"
  else
    echo "备份自检失败：pg_restore 读不出归档" >&2
    exit 1
  fi
fi

# 滚动保留：按修改时间留最近 KEEP 份。
# 注意 `ls -1t` 失败（目录为空）时不要因 `set -e` 直接退出，故加 `|| true`。
{ ls -1t "$DEST"/app-*.dump "$DEST"/app-*.sql 2>/dev/null || true; } \
  | tail -n "+$((KEEP + 1))" \
  | while IFS= read -r old; do
      rm -f "$old"
    done

echo "完成。本地保留最近 $KEEP 份。"
