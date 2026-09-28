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
        json={"term_name": "测试学期", "week1_monday": "2026-09-07", "end_date": "2027-01-10", "courses": courses},
    )
    assert commit.status_code == 201, commit.text
    day = authenticated_client.get("/api/v1/courses?date=2026-09-28").json()
    assert day["week"] == 4
    assert day["courses"][0]["start_time"] == "09:50"
    outside = authenticated_client.get("/api/v1/courses?date=2027-01-11").json()
    assert outside["term"] is None


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
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        assert (
            conn.execute("SELECT title FROM todos WHERE id=1").fetchone()[0]
            == "Existing private task"
        )
        assert (
            conn.execute("SELECT course_name FROM courses WHERE id=1").fetchone()[0]
            == "Existing course"
        )
        term = conn.execute("SELECT end_date,end_date_inferred FROM terms WHERE id=1").fetchone()
        assert tuple(term) == ("2027-01-10", 1)
        task_columns = {row[1] for row in conn.execute("PRAGMA table_info(todos)")}
        assert {"start_date", "start_time"} <= task_columns
    assert list((tmp_path / "backups").glob("assistant-pre-migration-v1-*.sqlite3"))


def test_course_edits_single_occurrence_and_requires_delete_confirmation(authenticated_client) -> None:
    commit = authenticated_client.post("/api/v1/courses/import/commit", json={
        "term_name": "编辑测试学期", "week1_monday": "2026-09-07", "end_date": "2027-01-10",
        "courses": [{"course_name": "原课程", "weekday": 1, "start_period": 3, "end_period": 4}],
    })
    assert commit.status_code == 201, commit.text
    custom_time = authenticated_client.post("/api/v1/courses", json={
        "term_id": commit.json()["term_id"], "course_name": "自定义时间课", "weekday": 2,
        "start_time": "13:05", "end_time": "14:25",
    })
    assert custom_time.status_code == 201, custom_time.text
    assert custom_time.json()["start_time"] == "13:05"
    invalid_time = authenticated_client.post("/api/v1/courses", json={
        "term_id": commit.json()["term_id"], "course_name": "无效时间课", "weekday": 2,
        "start_time": "14:25", "end_time": "13:05",
    })
    assert invalid_time.status_code == 422
    course_id = authenticated_client.get("/api/v1/courses?date=2026-09-28").json()["courses"][0]["id"]

    adjusted = authenticated_client.put(f"/api/v1/courses/{course_id}/occurrences/2026-09-28", json={
        "action": "override", "location": "临时教室", "start_period": 5, "end_period": 6,
    })
    assert adjusted.status_code == 200, adjusted.text
    day = authenticated_client.get("/api/v1/courses?date=2026-09-28").json()
    assert day["courses"][0]["location"] == "临时教室"
    assert day["courses"][0]["start_period"] == 5
    assert day["courses"][0]["exception"]

    clock_adjusted = authenticated_client.put(f"/api/v1/courses/{course_id}/occurrences/2026-09-28", json={
        "action": "override", "start_time": "13:05", "end_time": "14:25",
    })
    assert clock_adjusted.status_code == 200, clock_adjusted.text
    custom_day = authenticated_client.get("/api/v1/courses?date=2026-09-28").json()
    assert custom_day["courses"][0]["start_time"] == "13:05"

    restored = authenticated_client.delete(f"/api/v1/courses/{course_id}/occurrences/2026-09-28")
    assert restored.status_code == 200
    assert authenticated_client.get("/api/v1/courses?date=2026-09-28").json()["courses"][0]["course_name"] == "原课程"

    refused = authenticated_client.delete(f"/api/v1/courses/{course_id}")
    assert refused.status_code == 400
    deleted = authenticated_client.delete(f"/api/v1/courses/{course_id}?confirm=true")
    assert deleted.status_code == 200


def test_course_reminder_batch_requires_preview_confirmation_and_rejects_stale_preview(authenticated_client) -> None:
    commit = authenticated_client.post("/api/v1/courses/import/commit", json={
        "term_name": "提醒测试学期", "week1_monday": "2026-09-07", "end_date": "2027-01-10",
        "courses": [
            {"course_name": "第三节课", "weekday": 1, "start_period": 3, "end_period": 4},
            {"course_name": "第八节课", "weekday": 2, "start_period": 8, "end_period": 10},
        ],
    })
    assert commit.status_code == 201, commit.text
    preview = authenticated_client.post("/api/v1/courses/reminders/preview", json={
        "start_periods": [3, 8], "enabled": True, "lead_minutes": 25, "umo": "wechat:test-user",
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["count"] == 2
    assert preview.json()["requires_confirmation"] is True
    preview_id = preview.json()["preview_id"]

    no_confirmation = authenticated_client.post("/api/v1/courses/reminders/apply", json={
        "preview_id": preview_id, "umo": "wechat:test-user",
    })
    assert no_confirmation.status_code == 400

    updated_course_id = preview.json()["courses"][0]["id"]
    changed = authenticated_client.patch(f"/api/v1/courses/{updated_course_id}", json={"course_name": "课程已修改"})
    assert changed.status_code == 200
    stale = authenticated_client.post("/api/v1/courses/reminders/apply", json={
        "preview_id": preview_id, "umo": "wechat:test-user", "confirmed": True,
    })
    assert stale.status_code == 409

    fresh = authenticated_client.post("/api/v1/courses/reminders/preview", json={
        "start_periods": [3, 8], "enabled": True, "lead_minutes": 25, "umo": "wechat:test-user",
    })
    applied = authenticated_client.post("/api/v1/courses/reminders/apply", json={
        "preview_id": fresh.json()["preview_id"], "umo": "wechat:test-user", "confirmed": True,
    })
    assert applied.status_code == 200, applied.text
    assert applied.json()["updated_count"] == 2
    assert {item["reminder_lead_minutes"] for item in applied.json()["courses"]} == {25}
