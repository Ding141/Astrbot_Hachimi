from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from personal_assistant.db import audit, connection, utc_now
from personal_assistant.schemas import ScheduleEventCreate, ScheduleEventPatch
from personal_assistant.security import request_actor
from personal_assistant.services.domain import (
    _event_payload,
    _events_for_date,
    _now_local,
    _schedule_conflicts,
)

router = APIRouter()


@router.get("/api/v1/schedule-events")
def list_schedule_events(
    from_date: date | None = None,
    to_date: date | None = None,
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    del actor
    first = from_date or _now_local().date()
    last = to_date or first + timedelta(days=13)
    if last < first or (last - first).days > 366:
        raise HTTPException(status_code=422, detail="查询区间需在1年以内")
    with connection() as conn:
        days = []
        current = first
        while current <= last:
            days.append({"date": current.isoformat(), "events": _events_for_date(conn, current)})
            current += timedelta(days=1)
        definitions = [
            _event_payload(row)
            for row in conn.execute(
                "SELECT * FROM schedule_events WHERE deleted_at IS NULL ORDER BY start_date,id"
            ).fetchall()
        ]
        return {
            "from_date": first.isoformat(),
            "to_date": last.isoformat(),
            "days": days,
            "items": definitions,
        }


@router.post("/api/v1/schedule-events", status_code=201)
def create_schedule_event(
    body: ScheduleEventCreate, actor: str = Depends(request_actor)
) -> dict[str, Any]:
    now = utc_now()
    start_date = body.event_date if body.frequency == "once" else body.start_date
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO schedule_events(title,notes,event_date,frequency,weekdays_json,start_date,end_date,start_period,end_period,start_time,end_time,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                body.title.strip(),
                body.notes,
                body.event_date.isoformat() if body.event_date else None,
                body.frequency,
                json.dumps(sorted(set(body.weekdays))),
                start_date.isoformat(),
                body.end_date.isoformat() if body.end_date else None,
                body.start_period,
                body.end_period,
                body.start_time.strftime("%H:%M") if body.start_time else None,
                body.end_time.strftime("%H:%M") if body.end_time else None,
                now,
                now,
            ),
        )
        event_id = int(cursor.lastrowid)
        row = conn.execute("SELECT * FROM schedule_events WHERE id=?", (event_id,)).fetchone()
        after = _event_payload(row)
        after["conflicts"] = _schedule_conflicts(conn, after, exclude_id=event_id)
        audit(conn, actor, "schedule_event", event_id, "create", None, after)
        return after


@router.patch("/api/v1/schedule-events/{event_id}")
def update_schedule_event(
    event_id: int,
    body: ScheduleEventPatch,
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    with connection() as conn:
        before_row = conn.execute(
            "SELECT * FROM schedule_events WHERE id=? AND deleted_at IS NULL", (event_id,)
        ).fetchone()
        if not before_row:
            raise HTTPException(status_code=404, detail="找不到个人安排")
        before = _event_payload(before_row)
        combined = {
            "title": before["title"],
            "notes": before["notes"],
            "frequency": before["frequency"],
            "event_date": before.get("event_date"),
            "start_date": before.get("start_date"),
            "end_date": before.get("end_date"),
            "weekdays": before["weekdays"],
            "start_period": before.get("start_period"),
            "end_period": before.get("end_period"),
            "start_time": before.get("start_time"),
            "end_time": before.get("end_time"),
        }
        if before.get("start_period"):
            combined["start_time"] = None
            combined["end_time"] = None
        patch_fields = body.model_dump(exclude_unset=True)
        if patch_fields.get("frequency") == "weekly" and before["frequency"] == "once":
            combined["event_date"] = None
        if patch_fields.get("frequency") == "once" and before["frequency"] == "weekly":
            combined["weekdays"] = []
        if any(patch_fields.get(key) is not None for key in ("start_time", "end_time")):
            combined["start_period"] = None
            combined["end_period"] = None
        if any(patch_fields.get(key) is not None for key in ("start_period", "end_period")):
            combined["start_time"] = None
            combined["end_time"] = None
        combined.update(patch_fields)
        try:
            validated = ScheduleEventCreate.model_validate(combined)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        event_start = (
            validated.event_date if validated.frequency == "once" else validated.start_date
        )
        fields = {
            "title": validated.title.strip(),
            "notes": validated.notes,
            "event_date": validated.event_date.isoformat() if validated.event_date else None,
            "frequency": validated.frequency,
            "weekdays_json": json.dumps(sorted(set(validated.weekdays))),
            "start_date": event_start.isoformat(),
            "end_date": validated.end_date.isoformat() if validated.end_date else None,
            "start_period": validated.start_period,
            "end_period": validated.end_period,
            "start_time": validated.start_time.strftime("%H:%M") if validated.start_time else None,
            "end_time": validated.end_time.strftime("%H:%M") if validated.end_time else None,
            "updated_at": utc_now(),
        }
        assignments = ",".join(f"{key}=?" for key in fields)
        conn.execute(
            f"UPDATE schedule_events SET {assignments} WHERE id=?", [*fields.values(), event_id]
        )
        after = _event_payload(
            conn.execute("SELECT * FROM schedule_events WHERE id=?", (event_id,)).fetchone()
        )
        after["conflicts"] = _schedule_conflicts(conn, after, exclude_id=event_id)
        audit(conn, actor, "schedule_event", event_id, "update", before, after)
        return after


@router.delete("/api/v1/schedule-events/{event_id}")
def delete_schedule_event(event_id: int, actor: str = Depends(request_actor)) -> dict[str, bool]:
    now = utc_now()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM schedule_events WHERE id=? AND deleted_at IS NULL", (event_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到个人安排")
        before = dict(row)
        conn.execute(
            "UPDATE schedule_events SET deleted_at=?,updated_at=? WHERE id=?", (now, now, event_id)
        )
        audit(conn, actor, "schedule_event", event_id, "delete", before, {"deleted_at": now})
    return {"deleted": True}
