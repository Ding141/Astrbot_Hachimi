from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError

from personal_assistant.db import audit, connection, utc_now
from personal_assistant.schemas import (
    CourseCreate,
    CourseImportCommit,
    CourseInput,
    CourseOccurrencePatch,
    CoursePatch,
    CourseReminderApply,
    CourseReminderPreview,
    TermPatch,
)
from personal_assistant.security import request_actor
from personal_assistant.services.domain import (
    _course_payload,
    _course_query_for_date,
    _events_for_date,
    _now_local,
)
from personal_assistant.timetable import (
    parse_weekday_grid_courses,
    parse_workbook_courses,
    period_range,
    workbook_info,
)

logger = logging.getLogger("personal_assistant")

router = APIRouter()


def _normalize_clock(value: str | None) -> str | None:
    return value[:5] if value else None


@router.get("/api/v1/courses")
def query_courses(
    course_date: date | None = Query(default=None, alias="date"),
    weekday: int | None = Query(default=None, ge=1, le=7),
    term_id: int | None = Query(default=None, gt=0),
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    del actor
    if course_date is None:
        today = _now_local().date()
        if weekday is not None:
            days_ahead = (weekday - today.isoweekday()) % 7
            course_date = today + timedelta(days=days_ahead)
        else:
            course_date = today
    with connection() as conn:
        result = _course_query_for_date(conn, course_date, term_id)
        result["events"] = _events_for_date(conn, course_date)
        return result


@router.get("/api/v1/courses/week")
def query_course_week(
    week_start: date | None = None,
    term_id: int | None = Query(default=None, gt=0),
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    del actor
    requested = week_start or _now_local().date()
    monday = requested - timedelta(days=requested.weekday())
    with connection() as conn:
        days = []
        for offset in range(7):
            day = monday + timedelta(days=offset)
            result = _course_query_for_date(conn, day, term_id)
            result["events"] = _events_for_date(conn, day)
            days.append(result)
        term = next((day["term"] for day in days if day["term"]), None)
        week = next((day["week"] for day in days if day["week"] is not None), None)
        return {
            "week_start": monday.isoformat(),
            "week_end": (monday + timedelta(days=6)).isoformat(),
            "term": term,
            "week": week,
            "days": days,
        }


def _cancel_course_reminders(conn, course_id: int, reason: str, *, after: date | None = None) -> int:
    rows = conn.execute(
        "SELECT id,source_key,status FROM reminders WHERE source_type='course' AND status IN ('pending','failed','uncertain') AND source_key LIKE ?",
        (f"course:{course_id}:%",),
    ).fetchall()
    changed = 0
    for row in rows:
        parts = str(row["source_key"] or "").split(":")
        if after is not None and len(parts) >= 4:
            try:
                if date.fromisoformat(parts[2]) <= after:
                    continue
            except ValueError:
                continue
        conn.execute(
            "UPDATE reminders SET status='cancelled',last_error=? WHERE id=?",
            (reason, row["id"]),
        )
        changed += 1
    return changed


@router.patch("/api/v1/terms/{term_id}")
def update_term(term_id: int, body: TermPatch, actor: str = Depends(request_actor)) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM terms WHERE id=?", (term_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到學期")
        start = date.fromisoformat(row["week1_monday"])
        if body.end_date < start:
            raise HTTPException(status_code=422, detail="学期结束日期不能早于第一周周一")
        before = dict(row)
        conn.execute(
            "UPDATE terms SET end_date=?,end_date_inferred=0 WHERE id=?",
            (body.end_date.isoformat(), term_id),
        )
        if body.end_date < date.fromisoformat(row["end_date"] or "9999-12-31"):
            courses = conn.execute("SELECT id FROM courses WHERE term_id=?", (term_id,)).fetchall()
            for course in courses:
                _cancel_course_reminders(conn, int(course["id"]), "term_ended", after=body.end_date)
        after = dict(conn.execute("SELECT * FROM terms WHERE id=?", (term_id,)).fetchone())
        audit(conn, actor, "term", term_id, "update_end_date", before, after)
        return after


@router.post("/api/v1/courses", status_code=201)
def create_course(body: CourseCreate, actor: str = Depends(request_actor)) -> dict[str, Any]:
    try:
        data = CourseInput.model_validate(body.model_dump(exclude={"term_id"})).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    start_default, end_default = period_range(data["start_period"], data["end_period"])
    data["start_time"] = data["start_time"] or start_default
    data["end_time"] = data["end_time"] or end_default
    if not data["start_time"] or not data["end_time"]:
        raise HTTPException(status_code=422, detail="节次超过默认时间表范围时，请明确填写开始和结束时刻")
    data["start_time"] = _normalize_clock(data["start_time"])
    data["end_time"] = _normalize_clock(data["end_time"])
    with connection() as conn:
        term = conn.execute("SELECT * FROM terms WHERE id=?", (body.term_id,)).fetchone()
        if not term:
            raise HTTPException(status_code=404, detail="找不到学期")
        now = utc_now()
        cursor = conn.execute(
            "INSERT INTO courses(term_id,course_name,weekday,start_period,end_period,start_time,end_time,weeks_json,week_parity,location,teacher,notes,reminder_enabled,reminder_lead_minutes,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.term_id, data["course_name"], data["weekday"], data["start_period"], data["end_period"],
             data["start_time"], data["end_time"], json.dumps(data["weeks"]), data["week_parity"],
             data["location"], data["teacher"], data["notes"], int(body.reminder_enabled), body.reminder_lead_minutes, now, now),
        )
        course_id = int(cursor.lastrowid)
        after = _course_payload(conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone())
        audit(conn, actor, "course", course_id, "create", None, after)
        return after


@router.patch("/api/v1/courses/{course_id}")
def update_course(course_id: int, body: CoursePatch, actor: str = Depends(request_actor)) -> dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=422, detail="没有可更新的课程设置")
    if any(value is None for value in patch.values()):
        raise HTTPException(status_code=422, detail="课程字段不能设为 null；请提供明确的新值")
    with connection() as conn:
        row = conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到课程")
        before = _course_payload(row)
        course_fields = {key: value for key, value in patch.items() if key not in {"reminder_enabled", "reminder_lead_minutes"}}
        if course_fields:
            merged = {key: before.get(key) for key in (
                "course_name", "weekday", "start_period", "end_period", "start_time", "end_time",
                "weeks", "week_parity", "location", "teacher", "notes",
            )}
            merged.update(course_fields)
            try:
                valid = CourseInput.model_validate(merged).model_dump(mode="json")
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if any(key in course_fields for key in ("start_period", "end_period")) and not any(key in course_fields for key in ("start_time", "end_time")):
                valid["start_time"], valid["end_time"] = period_range(valid["start_period"], valid["end_period"])
            if not valid["start_time"] or not valid["end_time"]:
                raise HTTPException(status_code=422, detail="节次超过默认时间表范围时，请明确填写开始和结束时刻")
            valid["start_time"] = _normalize_clock(valid["start_time"])
            valid["end_time"] = _normalize_clock(valid["end_time"])
            course_fields = {
                "course_name": valid["course_name"], "weekday": valid["weekday"],
                "start_period": valid["start_period"], "end_period": valid["end_period"],
                "start_time": valid["start_time"], "end_time": valid["end_time"],
                "weeks_json": json.dumps(valid["weeks"]), "week_parity": valid["week_parity"],
                "location": valid["location"], "teacher": valid["teacher"], "notes": valid["notes"],
            }
        fields = dict(course_fields)
        if "reminder_enabled" in patch:
            fields["reminder_enabled"] = int(patch["reminder_enabled"])
        if "reminder_lead_minutes" in patch:
            fields["reminder_lead_minutes"] = patch["reminder_lead_minutes"]
        fields["updated_at"] = utc_now()
        assignments = ",".join(f"{key}=?" for key in fields)
        conn.execute(f"UPDATE courses SET {assignments} WHERE id=?", [*fields.values(), course_id])
        if patch.get("reminder_enabled") is False:
            _cancel_course_reminders(conn, course_id, "course_disabled")
        elif any(key in patch for key in ("reminder_lead_minutes", "course_name", "weekday", "start_period", "end_period", "start_time", "end_time", "weeks", "week_parity", "location", "teacher", "notes")):
            _cancel_course_reminders(conn, course_id, "course_updated")
        if patch.get("reminder_enabled") is True:
            conn.execute(
                "UPDATE reminders SET status='pending',last_error='',attempt_count=0,next_attempt_at=NULL "
                "WHERE source_type='course' AND source_key LIKE ? AND status='cancelled' AND last_error='course_disabled'",
                (f"course:{course_id}:%",),
            )
        after = _course_payload(conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone())
        audit(conn, actor, "course", course_id, "update", before, after)
        return after


@router.delete("/api/v1/courses/{course_id}")
def delete_course(course_id: int, confirm: bool = Query(default=False), actor: str = Depends(request_actor)) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(status_code=400, detail="删除整门课程需要 confirm=true 明确确认")
    with connection() as conn:
        row = conn.execute("SELECT c.*,t.name AS term_name FROM courses c JOIN terms t ON t.id=c.term_id WHERE c.id=?", (course_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到课程")
        summary = {"course_name": row["course_name"], "term": row["term_name"]}
        _cancel_course_reminders(conn, course_id, "course_deleted")
        conn.execute("DELETE FROM courses WHERE id=?", (course_id,))
        audit(conn, actor, "course", course_id, "delete", summary, {"deleted": True})
    return {"deleted": True, "course_id": course_id, **summary}


@router.put("/api/v1/courses/{course_id}/occurrences/{occurrence_date}")
def set_course_occurrence(course_id: int, occurrence_date: date, body: CourseOccurrencePatch, actor: str = Depends(request_actor)) -> dict[str, Any]:
    with connection() as conn:
        course = conn.execute("SELECT c.*,t.week1_monday,t.end_date FROM courses c JOIN terms t ON t.id=c.term_id WHERE c.id=?", (course_id,)).fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="找不到课程")
        base = _course_query_for_date(conn, occurrence_date, int(course["term_id"]), apply_exceptions=False)["courses"]
        if not any(item["id"] == course_id for item in base):
            raise HTTPException(status_code=422, detail="该日期不是这门课的上课日期")
        values = body.model_dump(exclude_unset=True, mode="json")
        for key in ("start_time", "end_time"):
            if values.get(key):
                values[key] = _normalize_clock(values[key])
        if body.action == "cancelled":
            values = {"action": "cancelled"}
        elif not any(key != "action" for key in values):
            raise HTTPException(status_code=422, detail="请至少提供一项本次课程的调整")
        before_row = conn.execute("SELECT * FROM course_exceptions WHERE course_id=? AND occurrence_date=?", (course_id, occurrence_date.isoformat())).fetchone()
        before = dict(before_row) if before_row else None
        now = utc_now()
        columns = ("start_period", "end_period", "start_time", "end_time", "location", "teacher", "notes")
        previous = dict(before_row) if before_row else {}
        data = {key: previous.get(key) for key in columns}
        for key in columns:
            if key in values:
                data[key] = values[key]
        if body.action == "override":
            uses_periods = data["start_period"] is not None or data["end_period"] is not None
            uses_times = data["start_time"] is not None or data["end_time"] is not None
            if uses_periods and (data["start_period"] is None or data["end_period"] is None):
                raise HTTPException(status_code=422, detail="调整节次需要同时提供开始和结束节次")
            if uses_periods and data["end_period"] < data["start_period"]:
                raise HTTPException(status_code=422, detail="结束节次不能早于开始节次")
            if uses_periods and uses_times:
                if "start_period" in values or "end_period" in values:
                    data["start_time"], data["end_time"] = period_range(data["start_period"], data["end_period"])
                else:
                    data["start_period"] = data["end_period"] = None
            elif uses_times and (data["start_time"] is None or data["end_time"] is None):
                raise HTTPException(status_code=422, detail="调整时间需要同时提供开始和结束时间")
            elif uses_times and data["end_time"] <= data["start_time"]:
                raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
            if (data["start_time"] is None) != (data["end_time"] is None):
                raise HTTPException(status_code=422, detail="调整时间需要同时提供开始和结束时间")
            if data["start_time"] is not None and data["end_time"] <= data["start_time"]:
                raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
            if data["start_period"] is not None:
                data["start_time"], data["end_time"] = period_range(data["start_period"], data["end_period"])
                if not data["start_time"] or not data["end_time"]:
                    raise HTTPException(status_code=422, detail="节次超过默认时间表范围时，请明确填写开始和结束时刻")
        conn.execute(
            "INSERT INTO course_exceptions(course_id,occurrence_date,action,start_period,end_period,start_time,end_time,location,teacher,notes,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(course_id,occurrence_date) DO UPDATE SET "
            "action=excluded.action,start_period=excluded.start_period,end_period=excluded.end_period,start_time=excluded.start_time,end_time=excluded.end_time,location=excluded.location,teacher=excluded.teacher,notes=excluded.notes,updated_at=excluded.updated_at",
            (course_id, occurrence_date.isoformat(), body.action, data["start_period"], data["end_period"], data["start_time"], data["end_time"], data["location"], data["teacher"], data["notes"], now, now),
        )
        conn.execute("UPDATE courses SET updated_at=? WHERE id=?", (now, course_id))
        _cancel_course_reminders(conn, course_id, "course_exception")
        after = dict(conn.execute("SELECT * FROM course_exceptions WHERE course_id=? AND occurrence_date=?", (course_id, occurrence_date.isoformat())).fetchone())
        audit(conn, actor, "course_occurrence", f"{course_id}:{occurrence_date}", "update", before, after)
        return after


@router.delete("/api/v1/courses/{course_id}/occurrences/{occurrence_date}")
def restore_course_occurrence(course_id: int, occurrence_date: date, actor: str = Depends(request_actor)) -> dict[str, bool]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM course_exceptions WHERE course_id=? AND occurrence_date=?", (course_id, occurrence_date.isoformat())).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到本次课程调整")
        before = dict(row)
        conn.execute("DELETE FROM course_exceptions WHERE id=?", (row["id"],))
        conn.execute("UPDATE courses SET updated_at=? WHERE id=?", (utc_now(), course_id))
        _cancel_course_reminders(conn, course_id, "course_exception")
        audit(conn, actor, "course_occurrence", f"{course_id}:{occurrence_date}", "restore", before, None)
    return {"restored": True}


@router.get("/api/v1/courses/search")
def search_courses(
    q: str = Query(min_length=1, max_length=200), actor: str = Depends(request_actor)
) -> dict[str, Any]:
    del actor
    today = _now_local().date()
    needle = f"%{q.strip()}%"
    with connection() as conn:
        term = conn.execute(
            "SELECT * FROM terms WHERE week1_monday<=? AND (end_date IS NULL OR end_date>=?) ORDER BY week1_monday DESC LIMIT 1",
            (today.isoformat(), today.isoformat()),
        ).fetchone()
        if not term:
            return {"query": q, "term": None, "courses": []}
        rows = conn.execute(
            "SELECT * FROM courses WHERE term_id=? AND (course_name LIKE ? OR location LIKE ? OR teacher LIKE ?) "
            "ORDER BY weekday,COALESCE(start_period,99),start_time",
            (term["id"], needle, needle, needle),
        ).fetchall()
        return {"query": q, "term": term["name"], "courses": [_course_payload(row) for row in rows]}


@router.post("/api/v1/courses/import/preview")
async def preview_course_import(
    file: UploadFile = File(...),
    sheet_name: str = Form(default=""),
    header_row: int = Form(default=1, ge=1, le=100),
    mapping: str = Form(default=""),
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    del actor
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=415, detail="目前仅支持 .xlsx 文件")
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="课表文件不能超过 10 MB")
    try:
        info = workbook_info(content, sheet_name or None, header_row)
        if info.get("format") == "weekday_grid":
            parsed = parse_weekday_grid_courses(content, info["sheet_name"])
            return {**info, **parsed, "needs_mapping": False}
        if not mapping:
            return {**info, "needs_mapping": True}
        try:
            selected_mapping = json.loads(mapping)
            if not isinstance(selected_mapping, dict):
                raise ValueError("mapping 必须为对象")
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"列映射格式错误：{exc}") from exc
        parsed = parse_workbook_courses(content, sheet_name or None, header_row, selected_mapping)
        return {**info, **parsed, "needs_mapping": False}
    except HTTPException:
        raise
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Workbook parsing failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=422, detail="无法读取课表，请确认文件完整且格式受支持。"
        ) from exc


@router.post("/api/v1/courses/import/commit", status_code=201)
def commit_course_import(
    body: CourseImportCommit, actor: str = Depends(request_actor)
) -> dict[str, Any]:
    with connection() as conn:
        existing = conn.execute(
            "SELECT * FROM terms WHERE name=?", (body.term_name.strip(),)
        ).fetchone()
        if existing and not body.replace_existing:
            raise HTTPException(
                status_code=409,
                detail="该学期已存在；如要替换，请先确认并设置 replace_existing=true",
            )
        before = None
        if existing:
            old_courses = conn.execute(
                "SELECT COUNT(*) AS count FROM courses WHERE term_id=?", (existing["id"],)
            ).fetchone()["count"]
            before = {"term": dict(existing), "course_count": old_courses}
            old_course_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM courses WHERE term_id=?", (existing["id"],)
                ).fetchall()
            ]
            for course_id in old_course_ids:
                _cancel_course_reminders(conn, int(course_id), "course_deleted")
            conn.execute("DELETE FROM terms WHERE id=?", (existing["id"],))
        cursor = conn.execute(
            "INSERT INTO terms(name,week1_monday,end_date,end_date_inferred,created_at) VALUES(?,?,?,0,?)",
            (body.term_name.strip(), body.week1_monday.isoformat(), body.end_date.isoformat(), utc_now()),
        )
        term_id = int(cursor.lastrowid)
        for course in body.courses:
            data = course.model_dump(mode="json")
            period_start, period_end = period_range(data["start_period"], data["end_period"])
            data["start_time"] = data["start_time"] or period_start
            data["end_time"] = data["end_time"] or period_end
            if not data["start_time"] or not data["end_time"]:
                raise HTTPException(status_code=422, detail="节次超过默认时间表范围时，请明确填写开始和结束时刻")
            data["start_time"] = _normalize_clock(data["start_time"])
            data["end_time"] = _normalize_clock(data["end_time"])
            conn.execute(
                "INSERT INTO courses(term_id,course_name,weekday,start_period,end_period,start_time,end_time,weeks_json,week_parity,location,teacher,notes,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    term_id,
                    data["course_name"],
                    data["weekday"],
                    data["start_period"],
                    data["end_period"],
                    data["start_time"],
                    data["end_time"],
                    json.dumps(data["weeks"]),
                    data["week_parity"],
                    data["location"],
                    data["teacher"],
                    data["notes"],
                    utc_now(),
                    utc_now(),
                ),
            )
        after = {"term_id": term_id, "term_name": body.term_name, "course_count": len(body.courses)}
        audit(
            conn, actor, "course_import", term_id, "replace" if before else "create", before, after
        )
        return after


@router.get("/api/v1/terms")
def list_terms(actor: str = Depends(request_actor)) -> dict[str, Any]:
    del actor
    with connection() as conn:
        terms = conn.execute(
            "SELECT t.id,t.name,t.week1_monday,t.end_date,t.end_date_inferred,COUNT(c.id) AS course_count FROM terms t "
            "LEFT JOIN courses c ON c.term_id=t.id GROUP BY t.id ORDER BY t.week1_monday DESC"
        ).fetchall()
        today = _now_local().date().isoformat()
        active = next((int(term["id"]) for term in terms if term["week1_monday"] <= today and (not term["end_date"] or term["end_date"] >= today)), None)
        return {"items": [dict(term) for term in terms], "active_term_id": active}


@router.post("/api/v1/courses/reminders/preview")
def preview_course_reminder_batch(body: CourseReminderPreview, actor: str = Depends(request_actor)) -> dict[str, Any]:
    umo = body.umo.strip()
    if not umo:
        raise HTTPException(status_code=422, detail="请先绑定当前微信会话后再预览批量操作")
    with connection() as conn:
        term_id = body.term_id
        if term_id is None:
            today = _now_local().date().isoformat()
            active = conn.execute(
                "SELECT id FROM terms WHERE week1_monday<=? AND end_date>=? ORDER BY week1_monday DESC LIMIT 1",
                (today, today),
            ).fetchone()
            if not active:
                raise HTTPException(status_code=409, detail="当前没有有效学期，请先选择或导入学期")
            term_id = int(active["id"])
        term = conn.execute("SELECT * FROM terms WHERE id=?", (term_id,)).fetchone()
        if not term:
            raise HTTPException(status_code=404, detail="找不到目标学期")
        if body.course_ids:
            placeholders = ",".join("?" for _ in body.course_ids)
            rows = conn.execute(
                f"SELECT * FROM courses WHERE term_id=? AND id IN ({placeholders}) ORDER BY weekday,start_period,id",
                [term_id, *body.course_ids],
            ).fetchall()
            if len(rows) != len(set(body.course_ids)):
                raise HTTPException(status_code=422, detail="部分课程编号不属于所选学期")
        else:
            placeholders = ",".join("?" for _ in body.start_periods)
            rows = conn.execute(
                f"SELECT * FROM courses WHERE term_id=? AND start_period IN ({placeholders}) ORDER BY weekday,start_period,id",
                [term_id, *body.start_periods],
            ).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="没有找到符合条件的课程；没有执行任何修改")
        if len(rows) > 200:
            raise HTTPException(status_code=422, detail="单次批量操作最多预览200门课程，请缩小范围")
        preview_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(minutes=15)).isoformat(timespec="seconds")
        ids = [int(row["id"]) for row in rows]
        versions = {str(row["id"]): row["updated_at"] for row in rows}
        criteria = {"term_id": term_id, "start_periods": body.start_periods, "course_ids": body.course_ids}
        conn.execute(
            "INSERT INTO course_reminder_previews(umo,preview_id,actor,course_ids_json,expected_versions_json,criteria_json,enabled,lead_minutes,term_id,expires_at,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(umo) DO UPDATE SET preview_id=excluded.preview_id,actor=excluded.actor,course_ids_json=excluded.course_ids_json,expected_versions_json=excluded.expected_versions_json,criteria_json=excluded.criteria_json,enabled=excluded.enabled,lead_minutes=excluded.lead_minutes,term_id=excluded.term_id,expires_at=excluded.expires_at,created_at=excluded.created_at",
            (umo, preview_id, actor, json.dumps(ids), json.dumps(versions), json.dumps(criteria), int(body.enabled), body.lead_minutes, term_id, expires_at, now.isoformat(timespec="seconds")),
        )
        preview_courses = []
        for row in rows:
            item = _course_payload(row)
            preview_courses.append({"id": item["id"], "course_name": item["course_name"], "weekday": item["weekday"], "start_period": item["start_period"], "end_period": item["end_period"], "enabled": body.enabled, "lead_minutes": body.lead_minutes})
        return {"preview_id": preview_id, "expires_at": expires_at, "term": term["name"], "count": len(rows), "courses": preview_courses, "enabled": body.enabled, "lead_minutes": body.lead_minutes, "requires_confirmation": True}


@router.post("/api/v1/courses/reminders/apply")
def apply_course_reminder_batch(body: CourseReminderApply, actor: str = Depends(request_actor)) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="批量修改课程提醒需要在预览后明确确认")
    umo = body.umo.strip()
    if not umo:
        raise HTTPException(status_code=422, detail="请先绑定当前微信会话")
    with connection() as conn:
        preview = conn.execute("SELECT * FROM course_reminder_previews WHERE umo=?", (umo,)).fetchone()
        if not preview or (body.preview_id and preview["preview_id"] != body.preview_id):
            raise HTTPException(status_code=404, detail="找不到这次预览；请重新预览目标课程")
        if preview["actor"] != actor:
            raise HTTPException(status_code=403, detail="这次预览属于另一个操作来源，请重新预览")
        if datetime.fromisoformat(preview["expires_at"]) < datetime.now(timezone.utc):
            conn.execute("DELETE FROM course_reminder_previews WHERE umo=?", (umo,))
            raise HTTPException(status_code=410, detail="预览已过期，请重新预览后确认")
        ids = json.loads(preview["course_ids_json"])
        versions = json.loads(preview["expected_versions_json"])
        changed = []
        for course_id in ids:
            row = conn.execute("SELECT * FROM courses WHERE id=? AND term_id=?", (course_id, preview["term_id"])).fetchone()
            if not row or row["updated_at"] != versions.get(str(course_id)):
                raise HTTPException(status_code=409, detail="预览后课程信息已变化，请重新预览并確認")
            before = _course_payload(row)
            conn.execute(
                "UPDATE courses SET reminder_enabled=?,reminder_lead_minutes=?,updated_at=? WHERE id=?",
                (preview["enabled"], preview["lead_minutes"], utc_now(), course_id),
            )
            if not preview["enabled"]:
                _cancel_course_reminders(conn, course_id, "course_disabled")
            else:
                _cancel_course_reminders(conn, course_id, "course_updated")
            after = _course_payload(conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone())
            audit(conn, actor, "course", course_id, "batch_reminder_update", before, after)
            changed.append({"id": course_id, "course_name": after["course_name"], "reminder_enabled": bool(after["reminder_enabled"]), "reminder_lead_minutes": after["reminder_lead_minutes"]})
        conn.execute("DELETE FROM course_reminder_previews WHERE umo=?", (umo,))
        return {"updated_count": len(changed), "courses": changed, "enabled": bool(preview["enabled"]), "lead_minutes": preview["lead_minutes"], "confirmed": True}


@router.get("/api/v1/courses/{course_id}")
def get_course(course_id: int, actor: str = Depends(request_actor)) -> dict[str, Any]:
    del actor
    with connection() as conn:
        row = conn.execute(
            "SELECT c.*,t.name AS term_name,t.week1_monday,t.end_date FROM courses c JOIN terms t ON t.id=c.term_id WHERE c.id=?",
            (course_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到课程")
        return _course_payload(row)
