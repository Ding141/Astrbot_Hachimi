from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from personal_assistant.db import audit, connection
from personal_assistant.schemas import ReminderCreate, ReminderRetry
from personal_assistant.security import request_actor
from personal_assistant.services.domain import _add_reminder, _get_setting

router = APIRouter()


@router.get("/api/v1/reminders")
def list_reminders(
    status: str = Query(default="", pattern="^(|pending|sent|failed|uncertain|cancelled)$"),
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    del actor
    with connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE status=? ORDER BY remind_at DESC LIMIT 500",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reminders ORDER BY remind_at DESC LIMIT 500"
            ).fetchall()
        return {"items": [dict(row) for row in rows]}


@router.post("/api/v1/reminders", status_code=201)
def create_reminder(body: ReminderCreate, actor: str = Depends(request_actor)) -> dict[str, Any]:
    with connection() as conn:
        if body.todo_id is not None:
            todo = conn.execute(
                "SELECT * FROM todos WHERE id=? AND deleted_at IS NULL", (body.todo_id,)
            ).fetchone()
            if not todo:
                raise HTTPException(status_code=404, detail="关联的任务不存在")
        reminder_id = _add_reminder(
            conn, body.title.strip(), body.remind_at, body.todo_id, body.recipient_umo
        )
        after = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        audit(conn, actor, "reminder", reminder_id, "create", None, dict(after))
        return dict(after)


@router.delete("/api/v1/reminders/{reminder_id}")
def cancel_reminder(reminder_id: int, actor: str = Depends(request_actor)) -> dict[str, bool]:
    with connection() as conn:
        before_row = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        if not before_row:
            raise HTTPException(status_code=404, detail="找不到该提醒")
        before = dict(before_row)
        if before["status"] in {"sent", "sending"}:
            raise HTTPException(status_code=409, detail="已发送或正在发送的提醒不能取消")
        conn.execute("UPDATE reminders SET status='cancelled' WHERE id=?", (reminder_id,))
        audit(conn, actor, "reminder", reminder_id, "cancel", before, {"status": "cancelled"})
    return {"cancelled": True}


@router.post("/api/v1/reminders/{reminder_id}/retry")
def retry_reminder(
    reminder_id: int,
    body: ReminderRetry,
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="手动重试可能产生重复通知，请设置 confirm=true")
    with connection() as conn:
        row = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="找不到该提醒")
        before = dict(row)
        if before["status"] not in {"failed", "uncertain"}:
            raise HTTPException(status_code=409, detail="只有失败或结果不确定的提醒可以手动重试")
        recipient = before["recipient_umo"] or _get_setting(conn, "default_umo")
        conn.execute(
            "UPDATE reminders SET status='pending',attempt_count=0,last_error='',next_attempt_at=NULL,recipient_umo=? WHERE id=?",
            (recipient, reminder_id),
        )
        after = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        audit(conn, actor, "reminder", reminder_id, "manual_retry", before, dict(after))
        return dict(after)
