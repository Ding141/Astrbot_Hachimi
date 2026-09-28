from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends

from personal_assistant.config import LOCAL_TIMEZONE
from personal_assistant.db import audit, connection, utc_now
from personal_assistant.schemas import WeeklyReviewPut
from personal_assistant.security import request_actor
from personal_assistant.services.domain import _course_query_for_date, _events_for_date

router = APIRouter()


@router.get("/api/v1/weekly-reviews/{week_start}")
def get_weekly_review(week_start: date, actor: str = Depends(request_actor)) -> dict[str, Any]:
    del actor
    monday = week_start - timedelta(days=week_start.weekday())
    next_monday = monday + timedelta(days=7)
    start_utc = (
        datetime.combine(monday, time.min, LOCAL_TIMEZONE)
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )
    end_utc = (
        datetime.combine(next_monday, time.min, LOCAL_TIMEZONE)
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )
    with connection() as conn:
        review = conn.execute(
            "SELECT * FROM weekly_reviews WHERE week_start=?", (monday.isoformat(),)
        ).fetchone()
        completed = conn.execute(
            "SELECT id,title,completed_at FROM todos WHERE status='completed' AND completed_at>=? AND completed_at<? ORDER BY completed_at",
            (start_utc, end_utc),
        ).fetchall()
        open_tasks = conn.execute(
            "SELECT id,title,start_date,start_time,due_date,due_time FROM todos WHERE status='open' AND deleted_at IS NULL "
            "AND COALESCE(due_date,start_date)>=? AND COALESCE(due_date,start_date)<? "
            "ORDER BY COALESCE(start_date,due_date),start_time,due_date,due_time",
            (monday.isoformat(), next_monday.isoformat()),
        ).fetchall()
        next_week = []
        for offset in range(7):
            target = next_monday + timedelta(days=offset)
            next_week.append(
                {
                    "date": target.isoformat(),
                    "courses": _course_query_for_date(conn, target)["courses"],
                    "events": _events_for_date(conn, target),
                }
            )
        return {
            "week_start": monday.isoformat(),
            "week_end": (next_monday - timedelta(days=1)).isoformat(),
            "reflection": review["reflection"] if review else "",
            "completed": [dict(row) for row in completed],
            "unfinished": [dict(row) for row in open_tasks],
            "next_week": next_week,
        }


@router.put("/api/v1/weekly-reviews/{week_start}")
def save_weekly_review(
    week_start: date,
    body: WeeklyReviewPut,
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    monday = week_start - timedelta(days=week_start.weekday())
    now = utc_now()
    with connection() as conn:
        before_row = conn.execute(
            "SELECT * FROM weekly_reviews WHERE week_start=?", (monday.isoformat(),)
        ).fetchone()
        conn.execute(
            "INSERT INTO weekly_reviews(week_start,reflection,created_at,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(week_start) DO UPDATE SET reflection=excluded.reflection,updated_at=excluded.updated_at",
            (monday.isoformat(), body.reflection, now, now),
        )
        after_row = conn.execute(
            "SELECT * FROM weekly_reviews WHERE week_start=?", (monday.isoformat(),)
        ).fetchone()
        after = dict(after_row)
        audit(
            conn,
            actor,
            "weekly_review",
            monday.isoformat(),
            "save",
            dict(before_row) if before_row else None,
            after,
        )
        return after
