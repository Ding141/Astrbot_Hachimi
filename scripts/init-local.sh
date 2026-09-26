#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
umask 077
mkdir -p data/service data/astrbot backups

if [[ -e .env ]]; then
  printf '%s\n' '.env already exists; leaving your local credentials unchanged.'
  exit 0
fi

PA_WEB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
PA_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
PA_SERVICE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
PA_UID="$(id -u)"
PA_GID="$(id -g)"

cat > .env <<EOF
WEB_PORT=8080
ASTRBOT_WEB_PORT=6185
COOKIE_SECURE=false
TIMEZONE=Asia/Shanghai
APP_UID=${PA_UID}
APP_GID=${PA_GID}
WEB_PASSWORD=${PA_WEB_PASSWORD}
SESSION_SECRET=${PA_SESSION_SECRET}
SERVICE_API_TOKEN=${PA_SERVICE_TOKEN}
ASTRBOT_API_KEY=
ASTRBOT_IMAGE=soulter/astrbot:v4.28.1
WEATHER_LOCATION_NAME=
WEATHER_LATITUDE=
WEATHER_LONGITUDE=
NEWS_RSS_URLS=
EOF
chmod 600 .env

printf '\n本地配置已创建。首次网页管理密码请立即保存：\n%s\n\n' "$PA_WEB_PASSWORD"
printf '%s\n' 'API Key 和微信扫码配置暂未设置；后续可在 AstrBot WebUI 中配置。'
