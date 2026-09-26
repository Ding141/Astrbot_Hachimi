from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError

from personal_assistant.db import audit, connection, utc_now
from personal_assistant.schemas import CourseImportCommit, CoursePatch
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


@router.get("/api/v1/courses")
def query_courses(
    course_date: date | None = Query(default=None, alias="date"),
    weekday: int | None = Query(default=None, ge=1, le=7),
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
        result = _course_query_for_date(conn, course_date)
        result["events"] = _events_for_date(conn, course_date)
        return result


@router.get("/api/v1/courses/week")
def query_course_week(
    week_start: date | None = None,
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    del actor
    requested = week_start or _now_local().date()
    monday = requested - timedelta(days=requested.weekday())
    with connection() as conn:
        days = []
        for offset in range(7):
            day = monday + timedelta(days=offset)
            result = _course_query_for_date(conn, day)
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


@router.patch("/api/v1/courses/{course_id}")
def update_course(
    course_id: int, body: CoursePatch, actor: str = Depends(request_actor)
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=422, detail="没有可更新的课程设置")
    if any(value is None for value in fields.values()):
        raise HTTPException(status_code=422, detail="课程提醒设置不能设为 null")
    with connection() as conn:
        before_row = conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
        if not before_row:
            raise HTTPException(status_code=404, detail="找不到课程")
        before = dict(before_row)
        lead_changed = (
            "reminder_lead_minutes" in fields
            and fields["reminder_lead_minutes"] != before["reminder_lead_minutes"]
        )
        if "reminder_enabled" in fields:
            fields["reminder_enabled"] = int(fields["reminder_enabled"])
        assignments = ",".join(f"{key}=?" for key in fields)
        conn.execute(f"UPDATE courses SET {assignments} WHERE id=?", [*fields.values(), course_id])
        if fields.get("reminder_enabled") == 0:
            conn.execute(
                "UPDATE reminders SET status='cancelled',last_error='course_disabled' "
                "WHERE source_type='course' AND source_key LIKE ? AND status IN ('pending','failed')",
                (f"course:{course_id}:%",),
            )
        elif fields.get("reminder_enabled") == 1:
            if not lead_changed:
                conn.execute(
                    "UPDATE reminders SET status='pending',last_error='',attempt_count=0,next_attempt_at=NULL "
                    "WHERE source_type='course' AND source_key LIKE ? AND status='cancelled' AND last_error='course_disabled'",
                    (f"course:{course_id}:%",),
                )
        if lead_changed:
            conn.execute(
                "UPDATE reminders SET status='cancelled',last_error='course_updated' "
                "WHERE source_type='course' AND source_key LIKE ? AND status IN ('pending','failed')",
                (f"course:{course_id}:%",),
            )
            conn.execute(
                "UPDATE reminders SET last_error='course_updated' "
                "WHERE source_type='course' AND source_key LIKE ? AND status='cancelled' AND last_error='course_disabled'",
                (f"course:{course_id}:%",),
            )
        after_row = conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
        after = _course_payload(after_row)
        audit(conn, actor, "course", course_id, "update_reminder", before, after)
        return after


@router.get("/api/v1/courses/search")
def search_courses(
    q: str = Query(min_length=1, max_length=200), actor: str = Depends(request_actor)
) -> dict[str, Any]:
    del actor
    today = _now_local().date()
    monday = today - timedelta(days=today.weekday())
    needle = f"%{q.strip()}%"
    with connection() as conn:
        term = conn.execute(
            "SELECT * FROM terms WHERE week1_monday<=? ORDER BY week1_monday DESC LIMIT 1",
            (monday.isoformat(),),
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
                conn.execute(
                    "UPDATE reminders SET status='cancelled',last_error='course_updated' "
                    "WHERE source_type='course' AND source_key LIKE ? AND status='pending'",
                    (f"course:{course_id}:%",),
                )
            conn.execute("DELETE FROM terms WHERE id=?", (existing["id"],))
        cursor = conn.execute(
            "INSERT INTO terms(name,week1_monday,created_at) VALUES(?,?,?)",
            (body.term_name.strip(), body.week1_monday.isoformat(), utc_now()),
        )
        term_id = int(cursor.lastrowid)
        for course in body.courses:
            data = course.model_dump(mode="json")
            period_start, period_end = period_range(data["start_period"], data["end_period"])
            data["start_time"] = data["start_time"] or period_start
            data["end_time"] = data["end_time"] or period_end
            conn.execute(
                "INSERT INTO courses(term_id,course_name,weekday,start_period,end_period,start_time,end_time,weeks_json,week_parity,location,teacher,notes,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            "SELECT t.id,t.name,t.week1_monday,COUNT(c.id) AS course_count FROM terms t "
            "LEFT JOIN courses c ON c.term_id=t.id GROUP BY t.id ORDER BY t.week1_monday DESC"
        ).fetchall()
        return {"items": [dict(term) for term in terms]}
