from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse

from personal_assistant.config import TIMEZONE_NAME
from personal_assistant.db import connection, utc_now
from personal_assistant.security import request_actor

router = APIRouter()


@router.get("/api/v1/export.json")
def export_json(actor: str = Depends(request_actor)) -> Response:
    del actor
    with connection() as conn:
        payload = {
            "format": "personal-assistant-export",
            "version": 2,
            "exported_at": utc_now(),
            "timezone": TIMEZONE_NAME,
            "todos": [dict(row) for row in conn.execute("SELECT * FROM todos ORDER BY id")],
            "reminders": [dict(row) for row in conn.execute("SELECT * FROM reminders ORDER BY id")],
            "terms": [dict(row) for row in conn.execute("SELECT * FROM terms ORDER BY id")],
            "courses": [dict(row) for row in conn.execute("SELECT * FROM courses ORDER BY id")],
            "todo_series": [
                dict(row) for row in conn.execute("SELECT * FROM todo_series ORDER BY id")
            ],
            "schedule_events": [
                dict(row) for row in conn.execute("SELECT * FROM schedule_events ORDER BY id")
            ],
            "weekly_reviews": [
                dict(row)
                for row in conn.execute("SELECT * FROM weekly_reviews ORDER BY week_start")
            ],
            "period_times": [
                dict(row) for row in conn.execute("SELECT * FROM period_times ORDER BY period")
            ],
            "settings": [
                dict(row)
                for row in conn.execute(
                    "SELECT key,value,updated_at FROM settings WHERE key NOT LIKE '%secret%'"
                )
            ],
            "audit_log": [dict(row) for row in conn.execute("SELECT * FROM audit_log ORDER BY id")],
        }
    return JSONResponse(
        content=json.loads(json.dumps(payload, ensure_ascii=False)),
        headers={"Content-Disposition": 'attachment; filename="personal-assistant-export.json"'},
    )


@router.get("/api/v1/export.csv")
def export_csv(
    resource: str = Query(
        pattern="^(todos|reminders|courses|todo-series|schedule-events|weekly-reviews)$"
    ),
    actor: str = Depends(request_actor),
) -> StreamingResponse:
    del actor
    with connection() as conn:
        if resource == "todos":
            rows = conn.execute("SELECT * FROM todos ORDER BY id").fetchall()
        elif resource == "reminders":
            rows = conn.execute("SELECT * FROM reminders ORDER BY id").fetchall()
        elif resource == "courses":
            rows = conn.execute(
                "SELECT t.name AS term,c.* FROM courses c JOIN terms t ON t.id=c.term_id ORDER BY c.id"
            ).fetchall()
        elif resource == "todo-series":
            rows = conn.execute("SELECT * FROM todo_series ORDER BY id").fetchall()
        elif resource == "schedule-events":
            rows = conn.execute("SELECT * FROM schedule_events ORDER BY id").fetchall()
        else:
            rows = conn.execute("SELECT * FROM weekly_reviews ORDER BY week_start").fetchall()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else ["empty"])
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))
    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{resource}.csv"'},
    )


@router.get("/api/v1/audit")
def list_audit(
    limit: int = Query(default=100, ge=1, le=500), actor: str = Depends(request_actor)
) -> dict[str, Any]:
    del actor
    with connection() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return {"items": [dict(row) for row in rows]}
