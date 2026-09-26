#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
if [[ ! -f .env ]]; then
  ./scripts/init-local.sh
fi

if docker info >/dev/null 2>&1; then
  docker compose up --build -d
else
  sudo docker compose up --build -d
fi
printf '\n个人助手网页：http://127.0.0.1:%s\nAstrBot WebUI：http://127.0.0.1:%s\n' \
  "$(sed -n 's/^WEB_PORT=//p' .env | tail -n 1)" \
  "$(sed -n 's/^ASTRBOT_WEB_PORT=//p' .env | tail -n 1)"
