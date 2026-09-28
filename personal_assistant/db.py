from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from personal_assistant.config import BACKUP_DIR, DATABASE_PATH

SCHEMA_VERSION = 4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    with connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database version {current} is newer than this application supports ({SCHEMA_VERSION})."
            )
        if current > 0 and current < SCHEMA_VERSION and DATABASE_PATH.exists():
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = BACKUP_DIR / f"assistant-pre-migration-v{current}-{stamp}.sqlite3"
            with sqlite3.connect(target) as destination:
                conn.backup(destination)
            target.chmod(0o600)
        if current == 0:
            conn.executescript(
                """
                CREATE TABLE todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 3 CHECK(priority BETWEEN 1 AND 5),
                    due_date TEXT,
                    due_time TEXT,
                    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','completed')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    deleted_at TEXT
                );
                CREATE INDEX idx_todos_status_due ON todos(status, due_date, due_time);
                CREATE INDEX idx_todos_title ON todos(title);

                CREATE TABLE reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    todo_id INTEGER REFERENCES todos(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    recipient_umo TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','sending','sent','failed','uncertain','cancelled')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    next_attempt_at TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT
                );
                CREATE INDEX idx_reminders_due ON reminders(status, remind_at);

                CREATE TABLE terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    week1_monday TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                    course_name TEXT NOT NULL,
                    weekday INTEGER NOT NULL CHECK(weekday BETWEEN 1 AND 7),
                    start_period INTEGER,
                    end_period INTEGER,
                    start_time TEXT,
                    end_time TEXT,
                    weeks_json TEXT NOT NULL DEFAULT '[]',
                    week_parity TEXT NOT NULL DEFAULT 'all' CHECK(week_parity IN ('all','odd','even')),
                    location TEXT NOT NULL DEFAULT '',
                    teacher TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX idx_courses_term_day ON courses(term_id, weekday);

                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX idx_audit_created ON audit_log(created_at DESC);
                """
            )
            conn.execute("PRAGMA user_version = 1")
            current = 1
        if current < 2:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """CREATE TABLE todo_series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 3 CHECK(priority BETWEEN 1 AND 5),
                    frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekly')),
                    weekdays_json TEXT NOT NULL DEFAULT '[]',
                    start_date TEXT NOT NULL,
                    end_date TEXT,
                    due_time TEXT,
                    reminder_enabled INTEGER NOT NULL DEFAULT 1 CHECK(reminder_enabled IN (0,1)),
                    reminder_times_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                )"""
            )
            conn.execute(
                "ALTER TABLE todos ADD COLUMN parent_id INTEGER REFERENCES todos(id) ON DELETE SET NULL"
            )
            conn.execute(
                "ALTER TABLE todos ADD COLUMN series_id INTEGER REFERENCES todo_series(id) ON DELETE SET NULL"
            )
            conn.execute("ALTER TABLE todos ADD COLUMN occurrence_date TEXT")
            conn.execute(
                "ALTER TABLE todos ADD COLUMN recurrence_override INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute("CREATE INDEX idx_todos_parent ON todos(parent_id,status)")
            conn.execute("CREATE INDEX idx_todos_series_date ON todos(series_id,occurrence_date)")
            conn.execute(
                "CREATE UNIQUE INDEX idx_todos_series_occurrence ON todos(series_id,occurrence_date) "
                "WHERE series_id IS NOT NULL AND occurrence_date IS NOT NULL"
            )

            conn.execute("ALTER TABLE reminders ADD COLUMN body TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "ALTER TABLE reminders ADD COLUMN source_type TEXT NOT NULL DEFAULT 'manual'"
            )
            conn.execute("ALTER TABLE reminders ADD COLUMN source_key TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX idx_reminders_source_key ON reminders(source_key) WHERE source_key IS NOT NULL"
            )

            conn.execute(
                "ALTER TABLE courses ADD COLUMN reminder_enabled INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE courses ADD COLUMN reminder_lead_minutes INTEGER NOT NULL DEFAULT 10"
            )

            conn.execute(
                """CREATE TABLE schedule_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    event_date TEXT,
                    frequency TEXT NOT NULL DEFAULT 'once' CHECK(frequency IN ('once','weekly')),
                    weekdays_json TEXT NOT NULL DEFAULT '[]',
                    start_date TEXT NOT NULL,
                    end_date TEXT,
                    start_period INTEGER,
                    end_period INTEGER,
                    start_time TEXT,
                    end_time TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    CHECK((start_period IS NOT NULL AND end_period IS NOT NULL) OR
                          (start_time IS NOT NULL AND end_time IS NOT NULL))
                )"""
            )
            conn.execute(
                "CREATE INDEX idx_schedule_events_date ON schedule_events(start_date,end_date,frequency)"
            )
            conn.execute(
                """CREATE TABLE weekly_reviews (
                    week_start TEXT PRIMARY KEY,
                    reflection TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

            period_ranges = [
                (1, "08:00", "08:45"),
                (2, "08:50", "09:35"),
                (3, "09:50", "10:35"),
                (4, "10:40", "11:25"),
                (5, "11:30", "12:15"),
                (6, "14:00", "14:45"),
                (7, "14:50", "15:35"),
                (8, "15:50", "16:35"),
                (9, "16:40", "17:25"),
                (10, "17:30", "18:15"),
                (11, "19:00", "19:45"),
                (12, "19:50", "20:35"),
                (13, "20:40", "21:25"),
                (14, "21:30", "22:15"),
            ]
            conn.execute(
                """CREATE TABLE period_times (
                    period INTEGER PRIMARY KEY CHECK(period BETWEEN 1 AND 14),
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL
                )"""
            )
            conn.executemany(
                "INSERT INTO period_times(period,start_time,end_time) VALUES(?,?,?)", period_ranges
            )
            for period, start_time, end_time in period_ranges:
                conn.execute(
                    "UPDATE courses SET start_time=COALESCE(start_time,?) WHERE start_period=?",
                    (start_time, period),
                )
                conn.execute(
                    "UPDATE courses SET end_time=COALESCE(end_time,?) WHERE end_period=?",
                    (end_time, period),
                )

            defaults = {
                "daily_brief_enabled": "1",
                "daily_brief_time": "08:00",
                "weekly_review_enabled": "1",
                "weekly_review_weekday": "7",
                "weekly_review_time": "20:00",
            }
            for key, value in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                    (key, value, utc_now()),
                )
            conn.execute("PRAGMA user_version = 2")
            current = 2
        if current < 3:
            if not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "ALTER TABLE todos ADD COLUMN reminder_override INTEGER NOT NULL DEFAULT 0 CHECK(reminder_override IN (0,1))"
            )
            conn.execute("PRAGMA user_version = 3")
            current = 3
        if current < 4:
            conn.execute("ALTER TABLE terms ADD COLUMN end_date TEXT")
            conn.execute(
                "ALTER TABLE terms ADD COLUMN end_date_inferred INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "UPDATE terms SET end_date=date(week1_monday, '+125 days'),end_date_inferred=1 "
                "WHERE end_date IS NULL"
            )
            conn.execute("ALTER TABLE courses ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
            conn.execute("UPDATE courses SET updated_at=created_at WHERE updated_at=''")
            conn.execute(
                """CREATE TABLE course_exceptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                    occurrence_date TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('cancelled','override')),
                    start_period INTEGER,
                    end_period INTEGER,
                    start_time TEXT,
                    end_time TEXT,
                    location TEXT,
                    teacher TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(course_id, occurrence_date)
                )"""
            )
            conn.execute("ALTER TABLE todos ADD COLUMN important INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE todos ADD COLUMN urgent_override INTEGER CHECK(urgent_override IN (0,1))")
            conn.execute("UPDATE todos SET important=CASE WHEN priority>=3 THEN 1 ELSE 0 END")
            conn.execute("ALTER TABLE todo_series ADD COLUMN important INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE todo_series ADD COLUMN urgent_override INTEGER CHECK(urgent_override IN (0,1))")
            conn.execute("ALTER TABLE todo_series ADD COLUMN month_day INTEGER CHECK(month_day BETWEEN 1 AND 31)")
            conn.execute("UPDATE todo_series SET important=CASE WHEN priority>=3 THEN 1 ELSE 0 END")
            conn.execute(
                """CREATE TABLE todo_series_subtasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id INTEGER NOT NULL REFERENCES todo_series(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    deleted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "ALTER TABLE todos ADD COLUMN series_subtask_id INTEGER REFERENCES todo_series_subtasks(id) ON DELETE SET NULL"
            )
            conn.execute(
                "CREATE UNIQUE INDEX idx_todo_series_subtask_occurrence "
                "ON todos(parent_id,series_subtask_id) WHERE series_subtask_id IS NOT NULL"
            )
            conn.execute(
                """CREATE TABLE course_reminder_previews (
                    umo TEXT PRIMARY KEY,
                    preview_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    course_ids_json TEXT NOT NULL,
                    expected_versions_json TEXT NOT NULL,
                    criteria_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    lead_minutes INTEGER NOT NULL CHECK(lead_minutes BETWEEN 0 AND 180),
                    term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            conn.execute("PRAGMA user_version = 4")
        conn.execute(
            "UPDATE reminders SET status='uncertain', last_error='Service restarted while delivery was in progress; check before retrying.' WHERE status='sending'"
        )


def to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def audit(
    conn: sqlite3.Connection,
    actor: str,
    resource: str,
    resource_id: str | int,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log(actor,resource,resource_id,action,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            actor,
            resource,
            str(resource_id),
            action,
            json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
            json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
            utc_now(),
        ),
    )
