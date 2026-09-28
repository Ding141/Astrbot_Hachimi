from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from personal_assistant.config import TIMEZONE_NAME
from personal_assistant.db import audit, connection, utc_now
from personal_assistant.schemas import (
    BulkDeleteRequest,
    TodoCreate,
    TodoPatch,
    TodoSeriesCreate,
    TodoSeriesPatch,
)
from personal_assistant.security import request_actor
from personal_assistant.services.domain import (
    _add_reminder,
    _cancel_unsent_reminders,
    _materialize_todo_series,
    _now_local,
    _todo_payload,
)

router = APIRouter()


def _series_view(conn, series) -> dict[str, Any]:
    item = dict(series)
    item["frequency"] = "monthly" if item.get("month_day") else item["frequency"]
    item["weekdays"] = json.loads(item.pop("weekdays_json"))
    item["reminder_times"] = json.loads(item.pop("reminder_times_json"))
    item["reminder_enabled"] = bool(item["reminder_enabled"])
    item["important"] = bool(item.get("important", 0))
    item["urgent"] = bool(item["urgent_override"]) if item.get("urgent_override") is not None else None
    item["legacy_unbounded"] = item.get("end_date") is None
    return item


@router.get("/api/v1/todos")
def list_todos(
    q: str = "",
    status: str = Query(default="open", pattern="^(open|completed|all)$"),
    due: str = Query(default="", pattern="^(|today|upcoming|overdue)$"),
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    del actor
    clauses = ["deleted_at IS NULL"]
    params: list[Any] = []
    if status != "all":
        clauses.append("status=?")
        params.append(status)
    if q.strip():
        clauses.append("(title LIKE ? OR notes LIKE ? OR category LIKE ?)")
        needle = f"%{q.strip()}%"
        params.extend([needle, needle, needle])
    today = _now_local().date().isoformat()
    if due == "today":
        clauses.append("COALESCE(start_date,due_date)<=? AND COALESCE(due_date,start_date)>=?")
        params.extend([today, today])
    elif due == "upcoming":
        last_day = (_now_local().date() + timedelta(days=7)).isoformat()
        clauses.append("COALESCE(due_date,start_date)>? AND COALESCE(start_date,due_date)<=?")
        params.extend([today, last_day])
    elif due == "overdue":
        current_time = _now_local().strftime("%H:%M")
        clauses.append(
            "status='open' AND (COALESCE(due_date,start_date)<? OR "
            "(due_date=? AND due_time IS NOT NULL AND due_time<?) OR "
            "(due_date IS NULL AND start_date=? AND start_time IS NOT NULL AND start_time<?))"
        )
        params.extend([today, today, current_time, today, current_time])
    sql = (
        "SELECT * FROM todos WHERE "
        + " AND ".join(clauses)
        + " ORDER BY CASE WHEN COALESCE(start_date,due_date) IS NULL THEN 1 ELSE 0 END,"
        "COALESCE(start_date,due_date),start_time,due_date,due_time,important DESC,priority DESC,id DESC"
    )
    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return {"items": [_todo_payload(conn, row) for row in rows], "timezone": TIMEZONE_NAME}


@router.get("/api/v1/todos/calendar")
def todo_calendar(
    from_date: date = Query(),
    to_date: date = Query(),
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    del actor
    if to_date < from_date or (to_date - from_date).days > 41:
        raise HTTPException(status_code=422, detail="日历查询范围最多42天")
    today = _now_local().date()
    if to_date > today + timedelta(days=366):
        raise HTTPException(status_code=422, detail="日历最多查看未来一年")
    with connection() as conn:
        _materialize_todo_series(conn, to_date)
        rows = conn.execute(
            "SELECT * FROM todos WHERE deleted_at IS NULL AND COALESCE(start_date,due_date)<=? "
            "AND COALESCE(due_date,start_date)>=? ORDER BY COALESCE(start_date,due_date),start_time,due_date,due_time,important DESC,priority DESC,id",
            (to_date.isoformat(), from_date.isoformat()),
        ).fetchall()
        undated = conn.execute(
            "SELECT * FROM todos WHERE deleted_at IS NULL AND due_date IS NULL AND start_date IS NULL ORDER BY important DESC,priority DESC,id DESC LIMIT 200",
        ).fetchall()
        return {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "items": [_todo_payload(conn, row) for row in rows],
            "undated": [_todo_payload(conn, row) for row in undated],
            "timezone": TIMEZONE_NAME,
        }


@router.post("/api/v1/todos", status_code=201)
def create_todo(body: TodoCreate, actor: str = Depends(request_actor)) -> dict[str, Any]:
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO todos(title,notes,category,priority,important,urgent_override,start_date,start_time,due_date,due_time,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                body.title.strip(),
                body.notes,
                body.category,
                body.priority,
                int(body.important if body.important is not None else body.priority >= 3),
                None if body.urgent is None else int(body.urgent),
                body.start_date.isoformat() if body.start_date else None,
                body.start_time.strftime("%H:%M") if body.start_time else None,
                body.end_date.isoformat() if body.end_date else None,
                body.end_time.strftime("%H:%M") if body.end_time else None,
                now,
                now,
            ),
        )
        todo_id = int(cursor.lastrowid)
        for reminder in body.reminders:
            _add_reminder(conn, body.title.strip(), reminder.remind_at, todo_id)
        after = conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
        audit(conn, actor, "todo", todo_id, "create", None, dict(after))
        return _todo_payload(conn, after)


@router.get("/api/v1/todo-series")
def list_todo_series(actor: str = Depends(request_actor)) -> dict[str, Any]:
    del actor
    with connection() as conn:
        series_rows = conn.execute(
            "SELECT * FROM todo_series WHERE deleted_at IS NULL ORDER BY start_date DESC,id DESC"
        ).fetchall()
        result = []
        for series in series_rows:
            item = _series_view(conn, series)
            item["end_time"] = item.pop("due_time")
            item["instances"] = [
                _todo_payload(conn, row)
                for row in conn.execute(
                    "SELECT * FROM todos WHERE series_id=? AND deleted_at IS NULL ORDER BY due_date LIMIT 12",
                    (series["id"],),
                ).fetchall()
            ]
            result.append(item)
        return {"items": result}


@router.post("/api/v1/todo-series", status_code=201)
def create_todo_series(
    body: TodoSeriesCreate, actor: str = Depends(request_actor)
) -> dict[str, Any]:
    now = utc_now()
    reminder_times = sorted({value.strftime("%H:%M") for value in body.reminder_times})
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO todo_series(title,notes,category,priority,frequency,month_day,weekdays_json,start_date,end_date,start_time,due_time,important,urgent_override,reminder_enabled,reminder_times_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                body.title.strip(),
                body.notes,
                body.category,
                body.priority,
                "daily" if body.frequency == "monthly" else body.frequency,
                body.month_day,
                json.dumps(sorted(set(body.weekdays))),
                body.start_date.isoformat(),
                body.end_date.isoformat(),
                body.start_time.strftime("%H:%M") if body.start_time else None,
                body.end_time.strftime("%H:%M") if body.end_time else None,
                int(body.important if body.important is not None else body.priority >= 3),
                None if body.urgent is None else int(body.urgent),
                int(body.reminder_enabled),
                json.dumps(reminder_times),
                now,
                now,
            ),
        )
        series_id = int(cursor.lastrowid)
        _materialize_todo_series(conn)
        series = conn.execute("SELECT * FROM todo_series WHERE id=?", (series_id,)).fetchone()
        instances = conn.execute(
            "SELECT * FROM todos WHERE series_id=? ORDER BY occurrence_date LIMIT 12", (series_id,)
        ).fetchall()
        after = _series_view(conn, series)
        after["end_time"] = after.pop("due_time")
        after["instances"] = [_todo_payload(conn, row) for row in instances]
        audit(conn, actor, "todo_series", series_id, "create", None, after)
        return after


@router.patch("/api/v1/todo-series/{series_id}")
def update_todo_series(
    series_id: int,
    body: TodoSeriesPatch,
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    for key in (
        "title",
        "notes",
        "category",
        "priority",
        "important",
        "frequency",
        "month_day",
        "start_date",
        "weekdays",
        "reminder_enabled",
        "reminder_times",
    ):
        if key in fields and fields[key] is None:
            raise HTTPException(status_code=422, detail=f"{key} 不能设为 null")
    if "title" in fields and not fields["title"].strip():
        raise HTTPException(status_code=422, detail="任务标题不能为空")
    if "start_date" in fields:
        fields["start_date"] = fields["start_date"].isoformat() if fields["start_date"] else None
    if "end_date" in fields:
        if fields["end_date"] is None:
            raise HTTPException(status_code=422, detail="重复任务必须设置停止日期")
        fields["end_date"] = fields["end_date"].isoformat() if fields["end_date"] else None
    if "priority" in fields and "important" not in fields:
        fields["important"] = int(fields["priority"] >= 3)
    if "important" in fields:
        fields["important"] = int(fields["important"])
    if "urgent" in fields:
        urgent_value = fields.pop("urgent")
        fields["urgent_override"] = None if urgent_value is None else int(urgent_value)
    if "frequency" in fields and fields["frequency"] == "monthly":
        fields["frequency"] = "daily"
        fields.setdefault("weekdays_json", "[]")
    elif "frequency" in fields and fields["frequency"] in {"daily", "weekly"}:
        fields["month_day"] = None
    if "weekdays" in fields:
        fields["weekdays_json"] = json.dumps(sorted(set(fields.pop("weekdays"))))
    elif fields.get("frequency") == "daily":
        fields["weekdays_json"] = "[]"
    if "start_time" in fields:
        fields["start_time"] = fields["start_time"].strftime("%H:%M") if fields["start_time"] else None
    if "end_time" in fields:
        fields["due_time"] = fields.pop("end_time").strftime("%H:%M") if fields["end_time"] else None
    if "reminder_times" in fields:
        fields["reminder_times_json"] = json.dumps(
            sorted({value.strftime("%H:%M") for value in fields.pop("reminder_times")})
        )
    if "reminder_enabled" in fields:
        fields["reminder_enabled"] = int(fields["reminder_enabled"])
    with connection() as conn:
        before_row = conn.execute(
            "SELECT * FROM todo_series WHERE id=? AND deleted_at IS NULL", (series_id,)
        ).fetchone()
        if not before_row:
            raise HTTPException(status_code=404, detail="找不到重复任务")
        before = dict(before_row)
        candidate_month_day = fields.get("month_day", before["month_day"])
        candidate_frequency = (
            "monthly" if candidate_month_day else fields.get("frequency", before["frequency"])
        )
        candidate_weekdays = fields.get("weekdays_json", before["weekdays_json"])
        if candidate_frequency == "weekly" and not json.loads(candidate_weekdays):
            raise HTTPException(status_code=422, detail="每周重复需要至少选择一个星期")
        if candidate_frequency != "weekly" and json.loads(candidate_weekdays):
            raise HTTPException(status_code=422, detail="每日或每月重复不能设置星期")
        candidate_start = fields.get("start_date", before["start_date"])
        candidate_end = fields.get("end_date", before["end_date"])
        if candidate_end and candidate_start and candidate_end < candidate_start:
            raise HTTPException(status_code=422, detail="重复结束日期不能早于开始日期")
        rule_changed = any(
            key in fields for key in ("frequency", "month_day", "weekdays_json", "start_date", "end_date")
        )
        if rule_changed and not candidate_end:
            raise HTTPException(status_code=422, detail="修改重复规则时必须设置停止日期")
        if fields:
            rule_changed = any(
                key in fields for key in ("frequency", "month_day", "weekdays_json", "start_date", "end_date")
            )
            if fields:
                fields["updated_at"] = utc_now()
                assignments = ",".join(f"{name}=?" for name in fields)
                conn.execute(
                    f"UPDATE todo_series SET {assignments} WHERE id=?", [*fields.values(), series_id]
                )
            if rule_changed:
                conn.execute(
                    "UPDATE todos SET deleted_at=?,updated_at=? WHERE series_id=? AND status='open' AND deleted_at IS NULL "
                    "AND recurrence_override=0 AND due_date>=?",
                    (utc_now(), utc_now(), series_id, _now_local().date().isoformat()),
                )
            else:
                conn.execute(
                    "UPDATE todos SET title=(SELECT title FROM todo_series WHERE id=?),"
                    "notes=(SELECT notes FROM todo_series WHERE id=?),"
                    "category=(SELECT category FROM todo_series WHERE id=?),"
                    "priority=(SELECT priority FROM todo_series WHERE id=?),"
                    "important=(SELECT important FROM todo_series WHERE id=?),"
                    "urgent_override=(SELECT urgent_override FROM todo_series WHERE id=?),"
                    "start_time=(SELECT start_time FROM todo_series WHERE id=?),"
                    "due_time=(SELECT due_time FROM todo_series WHERE id=?),updated_at=? "
                    "WHERE series_id=? AND status='open' AND deleted_at IS NULL AND recurrence_override=0 AND due_date>=?",
                    (
                        series_id,
                        series_id,
                        series_id,
                        series_id,
                        series_id,
                        series_id,
                        series_id,
                        series_id,
                        utc_now(),
                        series_id,
                        _now_local().date().isoformat(),
                    ),
                )
            if rule_changed or "reminder_enabled" in fields or "reminder_times_json" in fields:
                conn.execute(
                    "UPDATE reminders SET status='cancelled',last_error='series_updated' "
                    "WHERE source_type='todo_series' AND source_key LIKE ? AND status='pending'",
                    (f"todo-series:{series_id}:%",),
                )
            _materialize_todo_series(conn)
        after_row = conn.execute("SELECT * FROM todo_series WHERE id=?", (series_id,)).fetchone()
        after = _series_view(conn, after_row)
        after["end_time"] = after.pop("due_time")
        audit(conn, actor, "todo_series", series_id, "update", before, after)
        return after


@router.delete("/api/v1/todo-series/{series_id}")
def delete_todo_series(series_id: int, actor: str = Depends(request_actor)) -> dict[str, Any]:
    today = _now_local().date().isoformat()
    now = utc_now()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM todo_series WHERE id=? AND deleted_at IS NULL", (series_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到重复任务")
        before = dict(row)
        conn.execute(
            "UPDATE todo_series SET deleted_at=?,updated_at=? WHERE id=?", (now, now, series_id)
        )
        conn.execute(
            "UPDATE todos SET deleted_at=?,updated_at=? WHERE series_id=? AND status='open' AND deleted_at IS NULL AND due_date>=?",
            (now, now, series_id, today),
        )
        conn.execute(
            "UPDATE reminders SET status='cancelled' WHERE source_type='todo_series' AND source_key LIKE ? AND status='pending'",
            (f"todo-series:{series_id}:%",),
        )
        audit(conn, actor, "todo_series", series_id, "delete_future", before, {"deleted_at": now})
    return {"deleted": True, "future_occurrences_cancelled": True}


@router.post("/api/v1/todos/bulk-delete")
def bulk_delete(body: BulkDeleteRequest, actor: str = Depends(request_actor)) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="批量删除需要 confirm=true 明确确认")
    now = utc_now()
    deleted = 0
    with connection() as conn:
        for todo_id in sorted(set(body.ids)):
            before_row = conn.execute(
                "SELECT * FROM todos WHERE id=? AND deleted_at IS NULL", (todo_id,)
            ).fetchone()
            if not before_row:
                continue
            target_before = dict(before_row)
            conn.execute(
                "UPDATE todos SET deleted_at=?,updated_at=?,recurrence_override=1 WHERE id=?",
                (now, now, todo_id),
            )
            _cancel_unsent_reminders(conn, todo_id, actor, "cancel_after_todo_bulk_delete")
            audit(conn, actor, "todo", todo_id, "bulk_delete", target_before, {"deleted_at": now})
            deleted += 1
    return {"deleted_count": deleted}


@router.patch("/api/v1/todos/{todo_id}")
def update_todo(
    todo_id: int,
    body: TodoPatch,
    scope: str | None = Query(default=None, pattern="^(occurrence|series)$"),
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    clear_start_date = fields.pop("clear_start_date", False)
    clear_start_time = fields.pop("clear_start_time", False)
    clear_end_date = bool(fields.pop("clear_end_date", False) | fields.pop("clear_due_date", False))
    clear_end_time = bool(fields.pop("clear_end_time", False) | fields.pop("clear_due_time", False))
    clear_notes = fields.pop("clear_notes", False)
    clear_category = fields.pop("clear_category", False)
    reminders_supplied = "reminders" in fields
    reminder_inputs = fields.pop("reminders", None)
    if reminders_supplied and reminder_inputs is None:
        raise HTTPException(status_code=422, detail="reminders 不能设为 null；传空数组可清除提醒")
    for key in ("title", "notes", "category", "priority"):
        if key in fields and fields[key] is None:
            raise HTTPException(
                status_code=422, detail=f"{key} 不能设为 null；如需清空，请使用对应的清除选项"
            )
    if "title" in fields and not fields["title"].strip():
        raise HTTPException(status_code=422, detail="任务标题不能为空")
    if "important" in fields and fields["important"] is None:
        raise HTTPException(status_code=422, detail="重要性不能设为 null")
    if "priority" in fields and "important" not in fields:
        fields["important"] = int(fields["priority"] >= 3)
    if "important" in fields:
        fields["important"] = int(fields["important"])
    if "urgent" in fields:
        urgent_value = fields.pop("urgent")
        fields["urgent_override"] = None if urgent_value is None else int(urgent_value)
    with connection() as conn:
        before_row = conn.execute(
            "SELECT * FROM todos WHERE id=? AND deleted_at IS NULL", (todo_id,)
        ).fetchone()
        if not before_row:
            raise HTTPException(status_code=404, detail="找不到该任务")
        before = dict(before_row)
        if before.get("series_id") and scope is None:
            raise HTTPException(
                status_code=409, detail="这是重复任务，请指定 scope=occurrence 或 scope=series"
            )
        if not before.get("series_id") and scope == "series":
            raise HTTPException(status_code=409, detail="该任务不属于重复系列")
        if clear_start_date:
            fields["start_date"] = None
            fields["start_time"] = None
        elif clear_start_time:
            fields["start_time"] = None
        if clear_end_date:
            fields["end_date"] = None
            fields["end_time"] = None
        elif clear_end_time:
            fields["end_time"] = None
        if fields.get("start_date") is None and "start_date" in fields:
            fields["start_time"] = None
        if fields.get("end_date") is None and "end_date" in fields:
            fields["end_time"] = None
        if clear_notes:
            fields["notes"] = ""
        if clear_category:
            fields["category"] = ""
        if "start_date" in fields and fields["start_date"] is not None:
            fields["start_date"] = fields["start_date"].isoformat()
        if "end_date" in fields:
            fields["due_date"] = fields.pop("end_date").isoformat() if fields["end_date"] else None
        for time_field in ("start_time", "end_time"):
            if time_field in fields:
                parsed_time = fields.pop(time_field)
                db_field = "due_time" if time_field == "end_time" else "start_time"
                fields[db_field] = parsed_time.strftime("%H:%M") if parsed_time else None
        candidate_start_date = fields.get("start_date", before.get("start_date"))
        candidate_start_time = fields.get("start_time", before.get("start_time"))
        candidate_end_date = fields.get("due_date", before.get("due_date"))
        candidate_end_time = fields.get("due_time", before.get("due_time"))
        if candidate_start_time and not candidate_start_date:
            raise HTTPException(status_code=422, detail="设置开始时刻时也需要提供开始日期")
        if candidate_end_time and not candidate_end_date:
            raise HTTPException(status_code=422, detail="设置结束时刻时也需要提供结束日期")
        if candidate_start_date and candidate_end_date:
            start = date.fromisoformat(candidate_start_date)
            end = date.fromisoformat(candidate_end_date)
            if end < start or (
                end == start
                and candidate_start_time
                and candidate_end_time
                and datetime.combine(end, time.fromisoformat(candidate_end_time))
                < datetime.combine(start, time.fromisoformat(candidate_start_time))
            ):
                raise HTTPException(status_code=422, detail="结束时间不能早于开始时间")
        if "title" in fields and fields["title"] is not None:
            fields["title"] = fields["title"].strip()
        if before.get("series_id") and scope == "series":
            if reminders_supplied:
                raise HTTPException(
                    status_code=422, detail="修改整个系列的提醒请使用 reminder_times"
                )
            if "start_date" in fields or "due_date" in fields or clear_start_date or clear_end_date:
                raise HTTPException(
                    status_code=422, detail="修改整个系列的日期范围请使用重复规则设置"
                )
            allowed = {
                key: value
                for key, value in fields.items()
                if key in {"title", "notes", "category", "priority", "important", "urgent_override", "start_time", "due_time"}
            }
            if not allowed:
                after = conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
                return _todo_payload(conn, after)
            allowed["updated_at"] = utc_now()
            series_assignments = ",".join(f"{column}=?" for column in allowed)
            conn.execute(
                f"UPDATE todo_series SET {series_assignments} WHERE id=?",
                [*allowed.values(), before["series_id"]],
            )
            conn.execute(
                "UPDATE todos SET title=(SELECT title FROM todo_series WHERE id=?),notes=(SELECT notes FROM todo_series WHERE id=?),"
                "category=(SELECT category FROM todo_series WHERE id=?),priority=(SELECT priority FROM todo_series WHERE id=?),"
                "important=(SELECT important FROM todo_series WHERE id=?),urgent_override=(SELECT urgent_override FROM todo_series WHERE id=?),"
                "start_time=(SELECT start_time FROM todo_series WHERE id=?),"
                "due_time=(SELECT due_time FROM todo_series WHERE id=?),updated_at=? WHERE series_id=? AND status='open' "
                "AND deleted_at IS NULL AND recurrence_override=0 AND due_date>=?",
                (
                    before["series_id"],
                    before["series_id"],
                    before["series_id"],
                    before["series_id"],
                    before["series_id"],
                    before["series_id"],
                    before["series_id"],
                    before["series_id"],
                    utc_now(),
                    before["series_id"],
                    _now_local().date().isoformat(),
                ),
            )
            if any(key in allowed for key in ("title", "start_time", "due_time")):
                conn.execute(
                    "UPDATE reminders SET status='cancelled',last_error='series_updated' "
                    "WHERE source_type='todo_series' AND source_key LIKE ? AND status='pending'",
                    (f"todo-series:{before['series_id']}:%",),
                )
                _materialize_todo_series(conn)
            after = conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
            audit(conn, actor, "todo_series", before["series_id"], "update", None, allowed)
            audit(conn, actor, "todo", todo_id, "update_series", before, dict(after))
            return _todo_payload(conn, after)
        if not fields and not reminders_supplied:
            raise HTTPException(status_code=422, detail="没有提供要修改的任务内容")
        fields["updated_at"] = utc_now()
        assignments = ",".join(f"{column}=?" for column in fields)
        conn.execute(
            f"UPDATE todos SET {assignments} WHERE id=?",
            [*fields.values(), todo_id],
        )
        if before.get("series_id") and scope == "occurrence":
            conn.execute("UPDATE todos SET recurrence_override=1 WHERE id=?", (todo_id,))
            if any(key in fields for key in ("title", "start_date", "start_time", "due_date", "due_time")):
                conn.execute(
                    "UPDATE reminders SET status='cancelled',last_error='occurrence_updated' "
                    "WHERE todo_id=? AND source_type='todo_series' AND status='pending'",
                    (todo_id,),
                )
        if reminders_supplied:
            _cancel_unsent_reminders(conn, todo_id, actor, "replace_todo_reminders")
            current_title = fields.get("title", before["title"])
            for reminder in reminder_inputs:
                _add_reminder(conn, current_title, reminder["remind_at"], todo_id)
            if before.get("series_id"):
                conn.execute("UPDATE todos SET reminder_override=1 WHERE id=?", (todo_id,))
        after = conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
        audit(conn, actor, "todo", todo_id, "update", before, dict(after))
        return _todo_payload(conn, after)


@router.post("/api/v1/todos/{todo_id}/complete")
def complete_todo(todo_id: int, actor: str = Depends(request_actor)) -> dict[str, Any]:
    with connection() as conn:
        before_row = conn.execute(
            "SELECT * FROM todos WHERE id=? AND deleted_at IS NULL", (todo_id,)
        ).fetchone()
        if not before_row:
            raise HTTPException(status_code=404, detail="找不到该任务")
        before = dict(before_row)
        now = utc_now()
        conn.execute(
            "UPDATE todos SET status='completed',completed_at=?,updated_at=? WHERE id=?",
            (now, now, todo_id),
        )
        _cancel_unsent_reminders(conn, todo_id, actor, "cancel_after_todo_complete")
        after = conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
        audit(conn, actor, "todo", todo_id, "complete", before, dict(after))
        return _todo_payload(conn, after)


@router.delete("/api/v1/todos/{todo_id}")
def delete_todo(
    todo_id: int,
    scope: str | None = Query(default=None, pattern="^(occurrence|series)$"),
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    with connection() as conn:
        before_row = conn.execute(
            "SELECT * FROM todos WHERE id=? AND deleted_at IS NULL", (todo_id,)
        ).fetchone()
        if not before_row:
            raise HTTPException(status_code=404, detail="找不到该任务")
        before = dict(before_row)
        if before.get("series_id") and scope is None:
            raise HTTPException(
                status_code=409, detail="这是重复任务，请指定 scope=occurrence 或 scope=series"
            )
        if not before.get("series_id") and scope == "series":
            raise HTTPException(status_code=409, detail="该任务不属于重复系列")
        now = utc_now()
        if before.get("series_id") and scope == "series":
            series_id = int(before["series_id"])
            conn.execute(
                "UPDATE todo_series SET deleted_at=?,updated_at=? WHERE id=?", (now, now, series_id)
            )
            conn.execute(
                "UPDATE todos SET deleted_at=?,updated_at=? WHERE series_id=? AND status='open' AND deleted_at IS NULL AND due_date>=?",
                (now, now, series_id, _now_local().date().isoformat()),
            )
            conn.execute(
                "UPDATE reminders SET status='cancelled' WHERE source_type='todo_series' AND source_key LIKE ? AND status='pending'",
                (f"todo-series:{series_id}:%",),
            )
            audit(conn, actor, "todo_series", series_id, "delete_future", None, {"deleted_at": now})
            return {
                "deleted": True,
                "scope": "series",
                "recoverable_from": "JSON export or database backup",
            }
        conn.execute(
            "UPDATE todos SET deleted_at=?,updated_at=?,recurrence_override=1 WHERE id=?",
            (now, now, todo_id),
        )
        _cancel_unsent_reminders(conn, todo_id, actor, "cancel_after_todo_delete")
        audit(
            conn,
            actor,
            "todo",
            todo_id,
            "delete",
            before,
            {"deleted_at": now, "scope": scope or "occurrence"},
        )
    return {
        "deleted": True,
        "scope": scope or "occurrence",
        "recoverable_from": "JSON export or database backup",
    }
