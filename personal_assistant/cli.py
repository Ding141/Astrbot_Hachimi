from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from personal_assistant.config import DATABASE_PATH

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "./backups")).resolve()


def backup_database() -> Path:
    if not DATABASE_PATH.exists():
        raise SystemExit(f"Database does not exist yet: {DATABASE_PATH}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = BACKUP_DIR / f"assistant-{stamp}.sqlite3"
    with sqlite3.connect(DATABASE_PATH) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    target.chmod(0o600)
    return target


def restore_database(source_path: str) -> Path:
    source = Path(source_path).resolve()
    if source.parent != BACKUP_DIR or not source.is_file():
        raise SystemExit(f"Restore file must be a file directly inside {BACKUP_DIR}")
    with sqlite3.connect(source) as check:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SystemExit(f"Backup integrity check failed: {result}")
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = DATABASE_PATH.with_name(DATABASE_PATH.name + ".restore.tmp")
    try:
        with sqlite3.connect(source) as backup, sqlite3.connect(temp_path) as destination:
            backup.backup(destination)
        temp_path.chmod(0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(DATABASE_PATH) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        os.replace(temp_path, DATABASE_PATH)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return DATABASE_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal assistant data backup tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="Create a consistent SQLite backup")
    restore_parser = commands.add_parser("restore", help="Restore from a SQLite backup")
    restore_parser.add_argument("backup_file")
    args = parser.parse_args()
    if args.command == "backup":
        print(backup_database())
    else:
        print(restore_database(args.backup_file))


if __name__ == "__main__":
    main()
