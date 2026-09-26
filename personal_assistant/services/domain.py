from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from personal_assistant.config import LOCAL_TIMEZONE
from personal_assistant.db import audit, connection, utc_now
from personal_assistant.timetable import period_range


def _now_local() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def _normalize_datetime(value: str) -> str:
    if "T" not in value and " " not in value:
        raise HTTPException(status_code=422, detail="提醒时间必须包含明确的日期和时刻")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"无效的提醒时间：{value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def _set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
        (key, value, utc_now()),
    )


def _todo_payload(conn, row) -> dict[str, Any]:
    item = dict(row)
    reminders = conn.execute(
        "SELECT id,title,remind_at,recipient_umo,status,attempt_count,last_error,created_at,sent_at "
        "FROM reminders WHERE todo_id=? AND status<>'cancelled' ORDER BY remind_at",
        (item["id"],),
    ).fetchall()
    item["reminders"] = [dict(reminder) for reminder in reminders]
    children = conn.execute(
        "SELECT id,title,status,due_date,due_time FROM todos WHERE parent_id=? AND deleted_at IS NULL ORDER BY id",
        (item["id"],),
    ).fetchall()
    item["children"] = [dict(child) for child in children]
    item["child_count"] = len(children)
    item["child_done"] = sum(child["status"] == "completed" for child in children)
    if item.get("series_id"):
        series = conn.execute(
            "SELECT frequency,weekdays_json,start_date,end_date,reminder_enabled,reminder_times_json FROM todo_series WHERE id=?",
            (item["series_id"],),
        ).fetchone()
        if series:
            item["recurrence"] = {
                "series_id": item["series_id"],
                "frequency": series["frequency"],
                "start_date": series["start_date"],
                "end_date": series["end_date"],
                "weekdays": json.loads(series["weekdays_json"]),
                "reminder_enabled": bool(series["reminder_enabled"]),
                "reminder_times": json.loads(series["reminder_times_json"]),
            }
    return item


def _cancel_unsent_reminders(conn, todo_id: int, actor: str, reason: str) -> None:
    rows = conn.execute(
        "SELECT * FROM reminders WHERE todo_id=? AND status IN ('pending','failed','uncertain')",
        (todo_id,),
    ).fetchall()
    for row in rows:
        before = dict(row)
        conn.execute("UPDATE reminders SET status='cancelled' WHERE id=?", (row["id"],))
        audit(
            conn,
            actor,
            "reminder",
            row["id"],
            reason,
            before,
            {"status": "cancelled"},
        )


def _add_reminder(conn, title: str, when: str, todo_id: int | None = None, umo: str = "") -> int:
    recipient = umo or _get_setting(conn, "default_umo")
    cursor = conn.execute(
        "INSERT INTO reminders(todo_id,title,remind_at,recipient_umo,status,created_at) VALUES(?,?,?,?,?,?)",
        (todo_id, title, _normalize_datetime(when), recipient, "pending", utc_now()),
    )
    return int(cursor.lastrowid)


def _queue_scheduled_reminder(
    conn,
    *,
    source_type: str,
    source_key: str,
    title: str,
    when_local: datetime,
    body: str = "",
    todo_id: int | None = None,
) -> None:
    aware = when_local.replace(tzinfo=LOCAL_TIMEZONE) if when_local.tzinfo is None else when_local
    remind_at = aware.astimezone(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO reminders(todo_id,title,body,remind_at,recipient_umo,status,created_at,source_type,source_key) "
        "VALUES(?,?,?,?,?,'pending',?,?,?) ON CONFLICT(source_key) WHERE source_key IS NOT NULL DO UPDATE SET "
        "title=excluded.title,body=excluded.body,remind_at=excluded.remind_at, "
        "status=CASE WHEN reminders.status='cancelled' AND reminders.last_error IN ('series_updated','schedule_disabled','occurrence_updated') THEN 'pending' ELSE reminders.status END, "
        "last_error=CASE WHEN reminders.status='cancelled' AND reminders.last_error IN ('series_updated','schedule_disabled','occurrence_updated') THEN '' ELSE reminders.last_error END "
        "WHERE reminders.status='pending' OR (reminders.status='cancelled' AND reminders.last_error IN ('series_updated','schedule_disabled','occurrence_updated'))",
        (
            todo_id,
            title,
            body,
            remind_at,
            _get_setting(conn, "default_umo"),
            utc_now(),
            source_type,
            source_key,
        ),
    )


def _series_matches(series, target: date) -> bool:
    first = date.fromisoformat(series["start_date"])
    last = date.fromisoformat(series["end_date"]) if series["end_date"] else None
    if target < first or (last and target > last):
        return False
    if series["frequency"] == "daily":
        return True
    return target.isoweekday() in json.loads(series["weekdays_json"])


def _materialize_todo_series(conn, through: date | None = None) -> int:
    today = _now_local().date()
    through = through or today + timedelta(days=90)
    series_rows = conn.execute("SELECT * FROM todo_series WHERE deleted_at IS NULL").fetchall()
    created = 0
    for series in series_rows:
        first = max(date.fromisoformat(series["start_date"]), today - timedelta(days=30))
        last = (
            min(date.fromisoformat(series["end_date"]), through) if series["end_date"] else through
        )
        if last < first:
            continue
        day = first
        reminder_times = json.loads(series["reminder_times_json"])
        while day <= last:
            if _series_matches(series, day):
                existing = conn.execute(
                    "SELECT id,status,deleted_at,recurrence_override FROM todos WHERE series_id=? AND occurrence_date=?",
                    (series["id"], day.isoformat()),
                ).fetchone()
                if existing is None:
                    cursor = conn.execute(
                        "INSERT INTO todos(title,notes,category,priority,due_date,due_time,status,created_at,updated_at,series_id,occurrence_date) "
                        "VALUES(?,?,?,?,?,?,'open',?,?,?,?)",
                        (
                            series["title"],
                            series["notes"],
                            series["category"],
                            series["priority"],
                            day.isoformat(),
                            series["due_time"],
                            utc_now(),
                            utc_now(),
                            series["id"],
                            day.isoformat(),
                        ),
                    )
                    created += 1
                    todo_id = int(cursor.lastrowid)
                else:
                    todo_id = int(existing["id"])
                    if (
                        existing["deleted_at"]
                        and existing["status"] == "open"
                        and not existing["recurrence_override"]
                    ):
                        conn.execute(
                            "UPDATE todos SET title=?,notes=?,category=?,priority=?,due_time=?,deleted_at=NULL,updated_at=? WHERE id=?",
                            (
                                series["title"],
                                series["notes"],
                                series["category"],
                                series["priority"],
                                series["due_time"],
                                utc_now(),
                                todo_id,
                            ),
                        )
                todo = conn.execute(
                    "SELECT id,title,status,recurrence_override,reminder_override FROM todos WHERE id=? AND deleted_at IS NULL",
                    (todo_id,),
                ).fetchone()
                if (
                    todo
                    and todo["status"] == "open"
                    and not todo["reminder_override"]
                    and series["reminder_enabled"]
                ):
                    for raw_time in reminder_times:
                        clock = time.fromisoformat(raw_time[:5])
                        when_local = datetime.combine(day, clock, LOCAL_TIMEZONE)
                        if when_local <= _now_local():
                            continue
                        _queue_scheduled_reminder(
                            conn,
                            source_type="todo_series",
                            source_key=f"todo-series:{series['id']}:{day.isoformat()}:{clock.strftime('%H:%M')}",
                            title=str(todo["title"]),
                            when_local=when_local,
                            todo_id=int(todo["id"]),
                        )
            day += timedelta(days=1)
    return created


def _course_query_for_date(conn, course_date: date) -> dict[str, Any]:
    monday = course_date - timedelta(days=course_date.weekday())
    term = conn.execute(
        "SELECT * FROM terms WHERE week1_monday<=? ORDER BY week1_monday DESC LIMIT 1",
        (monday.isoformat(),),
    ).fetchone()
    if not term:
        return {
            "date": course_date.isoformat(),
            "weekday": course_date.isoweekday(),
            "term": None,
            "week": None,
            "courses": [],
        }
    week_number = ((monday - date.fromisoformat(term["week1_monday"])).days // 7) + 1
    rows = conn.execute(
        "SELECT * FROM courses WHERE term_id=? AND weekday=? ORDER BY COALESCE(start_period,99),start_time,course_name",
        (term["id"], course_date.isoweekday()),
    ).fetchall()
    matched = []
    for row in rows:
        weeks = json.loads(row["weeks_json"])
        if weeks and week_number not in weeks:
            continue
        if row["week_parity"] == "odd" and week_number % 2 == 0:
            continue
        if row["week_parity"] == "even" and week_number % 2 != 0:
            continue
        matched.append(_course_payload(row))
    return {
        "date": course_date.isoformat(),
        "weekday": course_date.isoweekday(),
        "term": term["name"],
        "week": week_number,
        "courses": matched,
    }


def _event_matches(event, target: date) -> bool:
    first = date.fromisoformat(event["start_date"])
    last = date.fromisoformat(event["end_date"]) if event["end_date"] else None
    if target < first or (last and target > last):
        return False
    if event["frequency"] == "once":
        return target.isoformat() == event["event_date"]
    return target.isoweekday() in json.loads(event["weekdays_json"])


def _event_payload(row, target: date | None = None) -> dict[str, Any]:
    item = dict(row)
    item["weekdays"] = json.loads(item.pop("weekdays_json"))
    item["date"] = target.isoformat() if target else item.get("event_date") or item["start_date"]
    if item.get("start_period"):
        item["start_time"], item["end_time"] = period_range(
            item["start_period"], item["end_period"]
        )
    return item


def _events_for_date(conn, event_date: date) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM schedule_events WHERE deleted_at IS NULL").fetchall()
    matched = [_event_payload(row, event_date) for row in rows if _event_matches(row, event_date)]
    return sorted(matched, key=lambda event: (event.get("start_time") or "99:99", event["title"]))


def _clock_minutes(value: str | None) -> int | None:
    if not value:
        return None
    parsed = time.fromisoformat(value[:5])
    return parsed.hour * 60 + parsed.minute


def _event_dates(event: dict[str, Any], limit_days: int = 56) -> list[date]:
    first = date.fromisoformat(event.get("event_date") or event["start_date"])
    end_text = event.get("end_date")
    last = (
        min(date.fromisoformat(end_text), first + timedelta(days=limit_days))
        if end_text
        else first + timedelta(days=limit_days)
    )
    if event.get("frequency") == "once":
        return [first]
    return [
        first + timedelta(days=i)
        for i in range((last - first).days + 1)
        if _event_matches(event, first + timedelta(days=i))
    ]


def _schedule_conflicts(
    conn, candidate: dict[str, Any], exclude_id: int | None = None
) -> list[dict[str, str]]:
    start = _clock_minutes(candidate.get("start_time"))
    end = _clock_minutes(candidate.get("end_time"))
    if start is None or end is None:
        return []
    conflicts: list[dict[str, str]] = []
    for day in _event_dates(candidate):
        day_courses = _course_query_for_date(conn, day)["courses"]
        existing = _events_for_date(conn, day)
        for other in [*day_courses, *existing]:
            if not other.get("course_name") and other.get("id") == exclude_id:
                continue
            other_start = _clock_minutes(other.get("start_time"))
            other_end = _clock_minutes(other.get("end_time"))
            if (
                other_start is not None
                and other_end is not None
                and start < other_end
                and other_start < end
            ):
                conflicts.append(
                    {
                        "date": day.isoformat(),
                        "title": str(other.get("course_name") or other.get("title") or "已有安排"),
                        "type": "course" if other.get("course_name") else "event",
                    }
                )
    return conflicts[:20]


WEEKDAY_ZH = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}


def _display_course(course: dict[str, Any]) -> str:
    if course.get("start_period"):
        period_text = (
            f"第{course['start_period']}–{course.get('end_period') or course['start_period']}节"
        )
    else:
        period_text = ""
    clock_text = ""
    if course.get("start_time"):
        clock_text = f"{course['start_time']}–{course.get('end_time') or course['start_time']}"
    detail = "；".join(
        value
        for value in (
            f"地点：{course['location']}" if course.get("location") else "",
            f"老师：{course['teacher']}" if course.get("teacher") else "",
        )
        if value
    )
    when = "｜".join(value for value in (period_text, clock_text) if value)
    return f"• {when + '｜' if when else ''}{course['course_name']}" + (
        f"\n  {detail}" if detail else ""
    )


def _daily_brief_text(target: date) -> str:
    from personal_assistant.push_plugins import render_daily_brief

    return render_daily_brief(target)


def _weekly_review_text(week_start: date) -> str:
    next_start = week_start + timedelta(days=7)
    start_utc = (
        datetime.combine(week_start, time.min, LOCAL_TIMEZONE)
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )
    end_utc = (
        datetime.combine(next_start, time.min, LOCAL_TIMEZONE)
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )
    with connection() as conn:
        completed = conn.execute(
            "SELECT title FROM todos WHERE status='completed' AND completed_at>=? AND completed_at<? ORDER BY completed_at",
            (start_utc, end_utc),
        ).fetchall()
        unfinished = conn.execute(
            "SELECT title,due_date FROM todos WHERE status='open' AND deleted_at IS NULL AND due_date>=? AND due_date<? ORDER BY due_date,due_time",
            (week_start.isoformat(), next_start.isoformat()),
        ).fetchall()
        review = conn.execute(
            "SELECT reflection FROM weekly_reviews WHERE week_start=?", (week_start.isoformat(),)
        ).fetchone()
        next_week_events = sum(
            len(_events_for_date(conn, next_start + timedelta(days=i))) for i in range(7)
        )
        next_week_courses = sum(
            len(_course_query_for_date(conn, next_start + timedelta(days=i))["courses"])
            for i in range(7)
        )
    lines = [
        f"一周复盘｜{week_start.isoformat()} 至 {(next_start - timedelta(days=1)).isoformat()}"
    ]
    lines.append(f"本周完成 {len(completed)} 项任务，仍有 {len(unfinished)} 项待办。")
    if completed:
        lines.extend(["\n已完成：", *[f"• {row['title']}" for row in completed[:12]]])
    if unfinished:
        lines.extend(
            ["\n未完成：", *[f"• {row['title']}（{row['due_date']}）" for row in unfinished[:12]]]
        )
    lines.append(f"\n下周已有 {next_week_courses} 门课程、{next_week_events} 项个人安排。")
    lines.append("可以直接在微信里告诉我本周总结和下周任务/安排，也可以在网页的“周复盘”填写。")
    if review and review["reflection"]:
        lines.append(f"\n上次记录：{review['reflection']}")
    return "\n".join(lines)


def _course_payload(row) -> dict[str, Any]:
    item = dict(row)
    item["weeks"] = json.loads(item.pop("weeks_json"))
    if item.get("start_period") and not item.get("start_time"):
        item["start_time"], _ = period_range(item["start_period"], item.get("end_period"))
    if item.get("end_period") and not item.get("end_time"):
        _, item["end_time"] = period_range(item.get("start_period"), item["end_period"])
    return item
