#!/usr/bin/env sh
# 公网部署：申请 / 续期 TLS 证书（r97）
#
#   ./scripts/cert.sh init    首次签发（会临时停掉前端容器，用 80 端口做 standalone 验证）
#   ./scripts/cert.sh renew   续期（走 webroot，不停服；签完自动 reload nginx）
#
# 依赖：docker；deploy.env 里的 PUBLIC_DOMAIN / ACME_EMAIL。
# 证书落点：certs/fullchain.pem 与 certs/privkey.pem（nginx.prod.conf 只读这两个文件），
# 中间产物留在 certs/letsencrypt（certbot 自己的目录结构，续期要用）。
set -eu

cd "$(dirname "$0")/.."

MODE="${1:-}"
if [ "$MODE" != "init" ] && [ "$MODE" != "renew" ]; then
  echo "用法：$0 init|renew" >&2
  exit 2
fi

if [ ! -f deploy.env ]; then
  echo "缺少 deploy.env：先 cp deploy.env.example deploy.env 并填 PUBLIC_DOMAIN / ACME_EMAIL" >&2
  exit 1
fi

# shellcheck disable=SC1091
. ./deploy.env
: "${PUBLIC_DOMAIN:?deploy.env 里缺 PUBLIC_DOMAIN}"
: "${ACME_EMAIL:?deploy.env 里缺 ACME_EMAIL}"

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env"
CERT_DIR="$PWD/certs"
ACME_DIR="$PWD/certbot/www"

mkdir -p "$CERT_DIR/letsencrypt" "$ACME_DIR"

copy_out() {
  # certbot 产物 → nginx 读的固定文件名（避免把域名写死进 nginx 配置）。
  docker run --rm \
    -v "$CERT_DIR/letsencrypt:/etc/letsencrypt:ro" \
    -v "$CERT_DIR:/out" \
    alpine:3 sh -c "cp -f /etc/letsencrypt/live/$PUBLIC_DOMAIN/fullchain.pem /out/fullchain.pem && \
                    cp -f /etc/letsencrypt/live/$PUBLIC_DOMAIN/privkey.pem /out/privkey.pem && \
                    chmod 644 /out/fullchain.pem && chmod 600 /out/privkey.pem"
  echo "已更新证书文件：certs/fullchain.pem · certs/privkey.pem"
}

if [ "$MODE" = "init" ]; then
  if [ -f "$CERT_DIR/fullchain.pem" ]; then
    echo "证书已存在；续期请用：$0 renew" >&2
    exit 1
  fi
  echo "→ 停掉前端容器（80 端口要让给 standalone 验证）"
  $COMPOSE stop frontend >/dev/null 2>&1 || true
  echo "→ 向 Let's Encrypt 申请证书：$PUBLIC_DOMAIN"
  docker run --rm \
    -p 80:80 \
    -v "$CERT_DIR/letsencrypt:/etc/letsencrypt" \
    certbot/certbot certonly --standalone \
    -d "$PUBLIC_DOMAIN" \
    --email "$ACME_EMAIL" --agree-tos --no-eff-email \
    --non-interactive
  copy_out
  echo "→ 启动整栈（nginx 需要证书文件才能起）"
  $COMPOSE up -d
  echo "完成：https://$PUBLIC_DOMAIN"
  exit 0
fi

echo "→ 续期（webroot，不停服）"
docker run --rm \
  -v "$CERT_DIR/letsencrypt:/etc/letsencrypt" \
  -v "$ACME_DIR:/var/www/certbot" \
  certbot/certbot renew --webroot -w /var/www/certbot --non-interactive
copy_out
$COMPOSE exec -T frontend nginx -s reload
echo "完成：nginx 已 reload"
