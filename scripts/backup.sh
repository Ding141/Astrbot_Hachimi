#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
if docker info >/dev/null 2>&1; then
  docker compose exec -T assistant-api python -m personal_assistant.cli backup
else
  sudo docker compose exec -T assistant-api python -m personal_assistant.cli backup
fi
