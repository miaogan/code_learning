#!/usr/bin/env bash
# 生成/更新公网 Basic Auth 密码文件（frontend/.htpasswd，不入库、不进镜像）。
#
# 注意（r23 起）：产品级登录已取代 nginx Basic Auth，compose 不再挂载该文件。
# 本脚本仅供回滚到 r21 公网 Basic Auth 时使用，日常部署不需要运行。
#
# 用法：
#   scripts/gen-htpasswd.sh                    # 默认用户 skillcoach，随机密码
#   scripts/gen-htpasswd.sh owner MyPass123    # 指定用户与密码
#
# 依赖：openssl（Git Bash 自带）。生成的条目是 APR1（$apr1$），nginx 原生支持。

set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v openssl >/dev/null 2>&1; then
  echo "错误：未找到 openssl（Git Bash 自带；或安装 OpenSSL 后重试）" >&2
  exit 1
fi

USER_NAME="${1:-skillcoach}"
PASS="${2:-$(openssl rand -hex 8)}"
HASH="$(openssl passwd -apr1 "$PASS")"

printf '%s:%s\n' "$USER_NAME" "$HASH" > frontend/.htpasswd

echo "已写入 frontend/.htpasswd（该文件在 .gitignore 内，不会被提交）"
echo "  用户名: $USER_NAME"
echo "  密码:   $PASS"
echo
echo "改完密码后需要重建前端容器才生效：docker-compose up -d --force-recreate frontend"
