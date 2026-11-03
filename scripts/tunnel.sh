#!/usr/bin/env bash
# 用 cloudflared 把本机 compose 端口暴露到公网（手机随时可访问，不依赖局域网）。
#
# 前置：docker-compose up -d 已跑通，本机 http://localhost:${WEB_PORT}/ 可访问。
# 用法：scripts/tunnel.sh
#
# 注意：quick tunnel 的 URL 每次重启都会变；正式固定域名需 named tunnel + 自有域名。

set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${WEB_PORT:-8080}"

if ! command -v cloudflared >/dev/null 2>&1; then
  cat <<'EOF'
未检测到 cloudflared。安装任选其一：

  winget install --id Cloudflare.cloudflared -e

  或从 https://github.com/cloudflare/cloudflared/releases 下载
  cloudflared-windows-amd64.exe，改名为 cloudflared.exe 并放进 PATH。

装好后重跑：scripts/tunnel.sh
EOF
  exit 1
fi

echo "正在把 http://localhost:${PORT} 暴露到公网……"
echo "（启动后终端里会出现 https://xxxx.trycloudflare.com 地址，用手机打开即可）"
echo
exec cloudflared tunnel --url "http://localhost:${PORT}"
