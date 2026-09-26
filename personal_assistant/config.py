from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DATABASE_PATH = Path(env("DATABASE_PATH", "./data/assistant.sqlite3"))
BACKUP_DIR = Path(env("BACKUP_DIR", "./backups"))
TIMEZONE_NAME = env("TIMEZONE", "Asia/Shanghai")
try:
    LOCAL_TIMEZONE = ZoneInfo(TIMEZONE_NAME)
except ZoneInfoNotFoundError as exc:  # pragma: no cover - configuration guard
    raise RuntimeError(f"Unknown TIMEZONE: {TIMEZONE_NAME}") from exc

WEB_PASSWORD = env("WEB_PASSWORD")
SESSION_SECRET = env("SESSION_SECRET")
SERVICE_API_TOKEN = env("SERVICE_API_TOKEN")
COOKIE_SECURE = env("COOKIE_SECURE", "false").lower() == "true"
ASTRBOT_API_BASE_URL = env("ASTRBOT_API_BASE_URL", "http://astrbot:6185/api/v1").rstrip("/")
ASTRBOT_API_KEY = env("ASTRBOT_API_KEY")


def validate_secrets() -> None:
    missing = [
        name
        for name, value in (
            ("WEB_PASSWORD", WEB_PASSWORD),
            ("SESSION_SECRET", SESSION_SECRET),
            ("SERVICE_API_TOKEN", SERVICE_API_TOKEN),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required local credentials: "
            + ", ".join(missing)
            + ". Run ./scripts/init-local.sh and restart the service."
        )
