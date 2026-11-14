#!/usr/bin/env sh
# 纯 IP 公网部署：申请 / 续期 Let's Encrypt「IP 地址证书」（不用域名）
#
#   ./scripts/cert-ip.sh init     首次签发（临时停前端，standalone 占 80）
#   ./scripts/cert-ip.sh renew    续期（webroot，不停服；签完 copy_out + reload nginx）
#   ./scripts/cert-ip.sh status   查看当前证书有效期与 SAN
#
# 与 scripts/cert.sh（域名档）互不影响：本脚本只给「浏览器地址栏就是裸 IP」的场景用。
# 依赖：docker；deploy.env 里的 PUBLIC_IP。ACME_EMAIL 可留空（6 天证书靠自动化，不靠到期邮件）。
#
# 背景（2026-01-15 Let's Encrypt GA，Certbot 5.3/5.4 跟进）：
#   - IP 证书把 IPv4/IPv6 写进 SAN，浏览器访问 https://43.166.23.144 校验通过 = 绿锁；
#   - 强制 shortlived profile，有效期 160 小时（约 6.7 天），**必须全自动续期**；
#   - 挑战只支持 http-01 / tls-alpn-01（DNS-01 不能证明 IP 控制权），本脚本走 http-01，
#     所以轻量控制台必须放行该 IP 的 80；443 供业务访问；
#   - Certbot 的 nginx/apache installer 还不支持 IP 证书，故用 certonly + 手工 copy_out。
#
# 证书落点与域名档一致：certs/fullchain.pem + certs/privkey.pem（nginx.prod.conf 只读这两个）。
# 续期建议（160h 有效期，留足失败重试窗口）：
#   12 */12 * * * cd /srv/skillcoach && ./scripts/cert-ip.sh renew >> logs/cert-ip-renew.log 2>&1
set -eu

cd "$(dirname "$0")/.."

MODE="${1:-}"
case "$MODE" in
  init|renew) ;;
  status)
    openssl x509 -in certs/fullchain.pem -noout -dates -subject -ext subjectAltName
    exit 0 ;;
  *)
    echo "用法：$0 init|renew|status" >&2
    exit 2 ;;
esac

if [ ! -f deploy.env ]; then
  echo "缺少 deploy.env：先 cp deploy.env.example deploy.env 并填 PUBLIC_IP / ACME_EMAIL" >&2
  exit 1
fi

# shellcheck disable=SC1091
. ./deploy.env
: "${PUBLIC_IP:?deploy.env 里缺 PUBLIC_IP（纯 IP 证书签给这个地址）}"
CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot:latest}"
# ACME_EMAIL 允许留空：160 小时证书靠自动化续期，到期提醒邮件意义不大。
if [ -n "${ACME_EMAIL:-}" ]; then
  ACCOUNT_ARGS="--email $ACME_EMAIL"
else
  ACCOUNT_ARGS="--register-unsafely-without-email"
fi

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file deploy.env"
CERT_DIR="$PWD/certs"
ACME_DIR="$PWD/certbot/www"

mkdir -p "$CERT_DIR/letsencrypt" "$ACME_DIR" logs

copy_out() {
  # --cert-name "$PUBLIC_IP"（init 时指定）把 lineage 目录钉成 IP，
  # 避免 certbot 用别的命名规则导致这里找不到文件。
  docker run --rm \
    -v "$CERT_DIR/letsencrypt:/etc/letsencrypt:ro" \
    -v "$CERT_DIR:/out" \
    alpine:3 sh -c "cp -f /etc/letsencrypt/live/$PUBLIC_IP/fullchain.pem /out/fullchain.pem && \
                    cp -f /etc/letsencrypt/live/$PUBLIC_IP/privkey.pem /out/privkey.pem && \
                    chmod 644 /out/fullchain.pem && chmod 600 /out/privkey.pem"
  echo "已更新证书文件：certs/fullchain.pem · certs/privkey.pem"
}

if [ "$MODE" = "init" ]; then
  if [ -f "$CERT_DIR/fullchain.pem" ]; then
    echo "证书已存在；续期请用：$0 renew" >&2
    exit 1
  fi
  echo "→ certbot 版本（IP + webroot 需要 >= 5.4）"
  docker run --rm "$CERTBOT_IMAGE" --version
  echo "→ 停掉前端容器（80 端口让给 standalone 验证）"
  $COMPOSE stop frontend >/dev/null 2>&1 || true
  echo "→ 向 Let's Encrypt 申请 IP 地址证书：$PUBLIC_IP"
  docker run --rm \
    -p 80:80 \
    -v "$CERT_DIR/letsencrypt:/etc/letsencrypt" \
    "$CERTBOT_IMAGE" certonly --standalone \
    --preferred-profile shortlived \
    --ip-address "$PUBLIC_IP" \
    --cert-name "$PUBLIC_IP" \
    $ACCOUNT_ARGS --agree-tos --no-eff-email \
    --non-interactive
  copy_out
  echo "→ 启动整栈（nginx 需要证书文件才能起）"
  $COMPOSE up -d
  echo "完成：https://$PUBLIC_IP"
  echo "别忘了装续期定时任务：12 */12 * * * cd $PWD && ./scripts/cert-ip.sh renew >> logs/cert-ip-renew.log 2>&1"
  exit 0
fi

echo "→ 续期（webroot，不停服）"

# 无人值守的两类静默故障，实测都遇到过：
#   1) 上一次 renew 被 kill / 机器重启 → 孤儿 certbot 容器 + `.certbot.lock` 残留，
#      之后每次都报 "Another instance of Certbot is already running"，6 天证书直接过期；
#   2) 两次 cron 重叠 → 互相抢锁。
# 用宿主 flock 串行 + 固定容器名 + 每次先清残留，把这两类故障自愈掉。
if command -v flock >/dev/null 2>&1; then
  exec 9>"$PWD/logs/cert-ip-renew.lock"
  # 只收紧这个锁文件：不能对整个脚本开 umask 077，否则 certbot/www 下的
  # http-01 挑战文件会变成 600，nginx worker 读不到 → 6 天证书续期直接失败。
  chmod 600 "$PWD/logs/cert-ip-renew.lock"
  if ! flock -n 9; then
    echo "另一次续期正在运行，本次跳过"
    exit 0
  fi
fi

CERTBOT_NAME=skillcoach-certbot-renew
docker rm -f "$CERTBOT_NAME" >/dev/null 2>&1 || true
docker run --rm -v "$CERT_DIR/letsencrypt:/etc/letsencrypt" alpine:3 \
  sh -c 'rm -f /etc/letsencrypt/.certbot.lock' >/dev/null 2>&1 || true

if docker run --rm --name "$CERTBOT_NAME" \
  -v "$CERT_DIR/letsencrypt:/etc/letsencrypt" \
  -v "$ACME_DIR:/var/www/certbot" \
  "$CERTBOT_IMAGE" renew --webroot -w /var/www/certbot --non-interactive; then
  RENEW_RC=0
else
  RENEW_RC=$?
fi
docker rm -f "$CERTBOT_NAME" >/dev/null 2>&1 || true
if [ "$RENEW_RC" -ne 0 ]; then
  echo "certbot renew 失败（RC=$RENEW_RC），请检查 logs/cert-ip-renew.log 与公网 80 端口" >&2
  exit "$RENEW_RC"
fi

copy_out
$COMPOSE exec -T frontend nginx -s reload
echo "→ 当前证书有效期"
openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -enddate
# 6 天证书最怕「续期静默失败」：cron 日志没人看，面试当天才发现过期。
# 这里做最后一道硬守卫：剩余不足 48 小时就让脚本以非零退出，cron 日志里必然留痕。
if ! openssl x509 -checkend 172800 -noout -in "$CERT_DIR/fullchain.pem" >/dev/null 2>&1; then
  echo "错误：证书剩余有效期不足 48 小时，续期链路可能已失效，请立即检查 certbot 日志与 80 端口" >&2
  exit 1
fi
echo "完成：nginx 已 reload，证书剩余有效期 > 48h"
