from __future__ import annotations

import sqlite3
import zipfile
from io import BytesIO

from openpyxl import Workbook

from personal_assistant import db
from personal_assistant.timetable import validate_xlsx_archive


def workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["课程名称", "星期", "开始节次", "结束节次", "周次", "地点", "教师"])
    sheet.append(["安全测试课程", "周一", 3, 4, "1-16周", "A101", "测试教师"])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_course_preview_import_and_week_query(authenticated_client) -> None:
    file_content = workbook_bytes()
    preview = authenticated_client.post(
        "/api/v1/courses/import/preview",
        data={
            "sheet_name": "",
            "header_row": "1",
            "mapping": '{"course_name":"课程名称","weekday":"星期","start_period":"开始节次","end_period":"结束节次","weeks":"周次","location":"地点","teacher":"教师"}',
        },
        files={
            "file": (
                "course.xlsx",
                file_content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    courses = preview.json()["courses"]
    assert courses[0]["course_name"] == "安全测试课程"

    commit = authenticated_client.post(
        "/api/v1/courses/import/commit",
        json={"term_name": "测试学期", "week1_monday": "2026-09-07", "courses": courses},
    )
    assert commit.status_code == 201, commit.text
    day = authenticated_client.get("/api/v1/courses?date=2026-09-28").json()
    assert day["week"] == 4
    assert day["courses"][0]["start_time"] == "09:50"


def test_xlsx_archive_rejects_high_compression_ratio() -> None:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", b"0" * 1_000_000)
    try:
        validate_xlsx_archive(payload.getvalue())
    except ValueError as error:
        assert "压缩率异常" in str(error)
    else:
        raise AssertionError("high compression-ratio workbook was accepted")


def test_v1_migration_preserves_existing_todo_and_course(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "legacy-v1.sqlite3"
    monkeypatch.setattr(db, "DATABASE_PATH", database_path)
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    with sqlite3.connect(database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE todos (
              id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL DEFAULT '', priority INTEGER NOT NULL DEFAULT 3,
              due_date TEXT, due_time TEXT, status TEXT NOT NULL DEFAULT 'open',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT, deleted_at TEXT
            );
            CREATE TABLE reminders (
              id INTEGER PRIMARY KEY AUTOINCREMENT, todo_id INTEGER, title TEXT NOT NULL,
              remind_at TEXT NOT NULL, recipient_umo TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
              attempt_count INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
              next_attempt_at TEXT, created_at TEXT NOT NULL, sent_at TEXT
            );
            CREATE TABLE terms (
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
              week1_monday TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE courses (
              id INTEGER PRIMARY KEY AUTOINCREMENT, term_id INTEGER NOT NULL, course_name TEXT NOT NULL,
              weekday INTEGER NOT NULL, start_period INTEGER, end_period INTEGER, start_time TEXT, end_time TEXT,
              weeks_json TEXT NOT NULL DEFAULT '[]', week_parity TEXT NOT NULL DEFAULT 'all',
              location TEXT NOT NULL DEFAULT '', teacher TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, resource TEXT NOT NULL,
              resource_id TEXT NOT NULL, action TEXT NOT NULL, before_json TEXT, after_json TEXT,
              created_at TEXT NOT NULL
            );
            INSERT INTO todos(title,created_at,updated_at) VALUES('Existing private task','now','now');
            INSERT INTO terms(name,week1_monday,created_at) VALUES('Existing term','2026-09-07','now');
            INSERT INTO courses(term_id,course_name,weekday,created_at) VALUES(1,'Existing course',1,'now');
            PRAGMA user_version=1;
            """
        )

    db.initialize_database()
    with sqlite3.connect(database_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert (
            conn.execute("SELECT title FROM todos WHERE id=1").fetchone()[0]
            == "Existing private task"
        )
        assert (
            conn.execute("SELECT course_name FROM courses WHERE id=1").fetchone()[0]
            == "Existing course"
        )
    assert list((tmp_path / "backups").glob("assistant-pre-migration-v1-*.sqlite3"))
