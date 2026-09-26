#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s <backup-file-name-under-backups/>\n' "$0" >&2
  exit 2
fi
BACKUP_NAME="$1"
if [[ "$BACKUP_NAME" == */* || "$BACKUP_NAME" == *..* ]]; then
  printf '%s\n' 'Pass only a backup file name, not a path.' >&2
  exit 2
fi

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
if [[ ! -f "backups/$BACKUP_NAME" ]]; then
  printf 'Backup not found: backups/%s\n' "$BACKUP_NAME" >&2
  exit 1
fi

run_compose() {
  if docker info >/dev/null 2>&1; then
    docker compose "$@"
  else
    sudo docker compose "$@"
  fi
}

restart_api() { run_compose up -d assistant-api >/dev/null 2>&1 || true; }
trap restart_api EXIT
run_compose stop assistant-api
run_compose run --rm --no-deps assistant-api python -m personal_assistant.cli restore "/app/backups/$BACKUP_NAME"
run_compose up -d assistant-api
trap - EXIT
printf '%s\n' 'Restore complete.'
