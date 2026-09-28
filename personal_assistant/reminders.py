from __future__ import annotations

import asyncio
import json
import logging
import socket
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

from personal_assistant.config import ASTRBOT_API_BASE_URL, ASTRBOT_API_KEY, LOCAL_TIMEZONE
from personal_assistant.db import connection, utc_now
from personal_assistant.timetable import period_range

logger = logging.getLogger("personal_assistant.reminders")


def _send_via_astrbot(umo: str, text: str) -> tuple[str, str]:
    if not ASTRBOT_API_KEY:
        return "disabled", "AstrBot OpenAPI key is not configured."
    payload = json.dumps({"umo": umo, "message": text}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{ASTRBOT_API_BASE_URL}/im/message",
        data=payload,
        headers={"Authorization": f"Bearer {ASTRBOT_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(2000).decode("utf-8", errors="replace")
            if 200 <= response.status < 300:
                return "sent", ""
            if response.status >= 500:
                return "uncertain", f"AstrBot returned HTTP {response.status}: {body}"
            return "failed", f"AstrBot returned HTTP {response.status}: {body}"
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        if exc.code >= 500:
            return "uncertain", f"AstrBot returned HTTP {exc.code}: {body}"
        return "failed", f"AstrBot returned HTTP {exc.code}: {body}"
    except (TimeoutError, socket.timeout) as exc:
        return "uncertain", f"Send outcome is unknown after timeout: {exc}"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return "uncertain", f"Send outcome is unknown after timeout: {exc.reason}"
        return "retryable", f"Could not connect to AstrBot: {exc.reason}"
    except Exception as exc:  # A platform adapter failure must not stop the scheduler.
        return "uncertain", f"Unexpected send error: {type(exc).__name__}: {exc}"


def _enqueue(
    conn,
    *,
    key: str,
    source_type: str,
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
        "title=excluded.title,body=excluded.body,remind_at=excluded.remind_at,"
        "status=CASE WHEN reminders.status='cancelled' AND reminders.last_error IN "
        "('series_updated','schedule_disabled','course_disabled','course_updated','course_exception','term_ended') THEN 'pending' ELSE reminders.status END,"
        "last_error=CASE WHEN reminders.status='cancelled' AND reminders.last_error IN "
        "('series_updated','schedule_disabled','course_disabled','course_updated','course_exception','term_ended') THEN '' ELSE reminders.last_error END "
        "WHERE reminders.status='pending' OR (reminders.status='cancelled' AND reminders.last_error IN "
        "('series_updated','schedule_disabled','course_disabled','course_updated','course_exception','term_ended'))",
        (
            todo_id,
            title,
            body,
            remind_at,
            _get_setting(conn, "default_umo"),
            utc_now(),
            source_type,
            key,
        ),
    )


def _get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def _materialize_periodic_jobs() -> None:
    now = datetime.now(LOCAL_TIMEZONE)
    today = now.date()
    with connection() as conn:
        # Recurring Todo occurrences are stored separately, with a unique (series, date) key.
        from personal_assistant.app import _materialize_todo_series

        _materialize_todo_series(conn, today + timedelta(days=90))

        if _get_setting(conn, "daily_brief_enabled", "1") == "1":
            clock = time.fromisoformat(_get_setting(conn, "daily_brief_time", "08:00")[:5])
            _enqueue(
                conn,
                key=f"daily-brief:{today.isoformat()}",
                source_type="daily_brief",
                title="每日安排简报",
                when_local=datetime.combine(today, clock, LOCAL_TIMEZONE),
            )
        else:
            conn.execute(
                "UPDATE reminders SET status='cancelled',last_error='schedule_disabled' WHERE source_type='daily_brief' AND status='pending'"
            )

        review_day = int(_get_setting(conn, "weekly_review_weekday", "7"))
        days_ahead = (review_day - today.isoweekday()) % 7
        review_date = today + timedelta(days=days_ahead)
        if _get_setting(conn, "weekly_review_enabled", "1") == "1":
            clock = time.fromisoformat(_get_setting(conn, "weekly_review_time", "20:00")[:5])
            _enqueue(
                conn,
                key=f"weekly-review:{review_date.isoformat()}",
                source_type="weekly_review",
                title="周总结与下周安排",
                when_local=datetime.combine(review_date, clock, LOCAL_TIMEZONE),
            )
        else:
            conn.execute(
                "UPDATE reminders SET status='cancelled',last_error='schedule_disabled' WHERE source_type='weekly_review' AND status='pending'"
            )

        # Create course reminders for the next two weeks; unique keys prevent duplicates after restarts.
        for offset in range(15):
            target = today + timedelta(days=offset)
            term = conn.execute(
                "SELECT * FROM terms WHERE week1_monday<=? AND (end_date IS NULL OR end_date>=?) ORDER BY week1_monday DESC LIMIT 1",
                (target.isoformat(), target.isoformat()),
            ).fetchone()
            if not term:
                continue
            monday = target - timedelta(days=target.weekday())
            week_number = ((monday - date.fromisoformat(term["week1_monday"])).days // 7) + 1
            rows = conn.execute(
                "SELECT * FROM courses WHERE term_id=? AND weekday=? AND reminder_enabled=1",
                (term["id"], target.isoweekday()),
            ).fetchall()
            for course_row in rows:
                course = dict(course_row)
                weeks = json.loads(course["weeks_json"])
                if weeks and week_number not in weeks:
                    continue
                if course["week_parity"] == "odd" and week_number % 2 == 0:
                    continue
                if course["week_parity"] == "even" and week_number % 2 != 0:
                    continue
                exception = conn.execute(
                    "SELECT * FROM course_exceptions WHERE course_id=? AND occurrence_date=?",
                    (course["id"], target.isoformat()),
                ).fetchone()
                if exception:
                    if exception["action"] == "cancelled":
                        continue
                    for key in ("start_period", "end_period", "start_time", "end_time", "location", "teacher", "notes"):
                        if exception[key] is not None:
                            course[key] = exception[key]
                    if exception["start_period"] is not None or exception["end_period"] is not None:
                        course["start_time"], course["end_time"] = period_range(
                            course["start_period"], course["end_period"]
                        )
                start_time = course["start_time"]
                end_time = course["end_time"]
                if not start_time or not end_time:
                    mapped_start, mapped_end = period_range(
                        course["start_period"], course["end_period"]
                    )
                    start_time, end_time = start_time or mapped_start, end_time or mapped_end
                if not start_time:
                    continue
                start_clock = time.fromisoformat(start_time[:5])
                class_start = datetime.combine(target, start_clock, LOCAL_TIMEZONE)
                lead = int(course["reminder_lead_minutes"])
                alert_at = class_start - timedelta(minutes=lead)
                if alert_at <= now:
                    continue
                periods = (
                    f"第{course['start_period']}–{course['end_period']}节"
                    if course["start_period"]
                    else ""
                )
                details = [f"{periods} {start_time}–{end_time}".strip()]
                if course["location"]:
                    details.append(f"地点：{course['location']}")
                if course["teacher"]:
                    details.append(f"老师：{course['teacher']}")
                body = f"⏰ 课前提醒：{course['course_name']}\n" + "\n".join(details)
                _enqueue(
                    conn,
                    key=f"course:{course['id']}:{target.isoformat()}:{lead}",
                    source_type="course",
                    title=f"{course['course_name']}课前提醒",
                    when_local=alert_at,
                    body=body,
                )


def _claim_due() -> list[dict[str, object]]:
    now = utc_now()
    claimed: list[dict[str, object]] = []
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status='pending' AND recipient_umo<>'' AND remind_at<=? "
            "AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY remind_at LIMIT 20",
            (now, now),
        ).fetchall()
        for row in rows:
            updated = conn.execute(
                "UPDATE reminders SET status='sending',attempt_count=attempt_count+1 WHERE id=? AND status='pending'",
                (row["id"],),
            )
            if updated.rowcount:
                claimed.append(dict(row))
    return claimed


def _finish(reminder_id: int, outcome: str, detail: str) -> None:
    current = utc_now()
    with connection() as conn:
        row = conn.execute(
            "SELECT attempt_count FROM reminders WHERE id=?", (reminder_id,)
        ).fetchone()
        attempts = row["attempt_count"] if row else 1
        if outcome == "sent":
            conn.execute(
                "UPDATE reminders SET status='sent',sent_at=?,last_error='',next_attempt_at=NULL WHERE id=?",
                (current, reminder_id),
            )
        elif outcome == "retryable" and attempts < 3:
            next_attempt = (datetime.now(timezone.utc) + timedelta(minutes=5 * attempts)).isoformat(
                timespec="seconds"
            )
            conn.execute(
                "UPDATE reminders SET status='pending',last_error=?,next_attempt_at=? WHERE id=?",
                (detail[:2000], next_attempt, reminder_id),
            )
        else:
            status = "uncertain" if outcome == "uncertain" else "failed"
            conn.execute(
                "UPDATE reminders SET status=?,last_error=?,next_attempt_at=NULL WHERE id=?",
                (status, detail[:2000], reminder_id),
            )


def _format_message(reminder: dict[str, object]) -> str:
    source_type = str(reminder.get("source_type") or "manual")
    if reminder.get("body"):
        return str(reminder["body"])
    local_time = datetime.fromisoformat(str(reminder["remind_at"])).astimezone(LOCAL_TIMEZONE)
    if source_type == "daily_brief":
        from personal_assistant.app import _daily_brief_text

        return _daily_brief_text(local_time.date())
    if source_type == "weekly_review":
        from personal_assistant.app import _weekly_review_text

        monday = local_time.date() - timedelta(days=local_time.date().weekday())
        return _weekly_review_text(monday)
    return f"⏰ 提醒：{reminder['title']}"


async def process_due_reminders() -> None:
    if not ASTRBOT_API_KEY:
        return
    for reminder in _claim_due():
        message = await asyncio.to_thread(_format_message, reminder)
        outcome, detail = await asyncio.to_thread(
            _send_via_astrbot,
            str(reminder["recipient_umo"]),
            message,
        )
        _finish(int(reminder["id"]), outcome, detail)


async def scheduler_loop() -> None:
    last_materialized = 0.0
    while True:
        try:
            if datetime.now().timestamp() - last_materialized >= 60:
                await asyncio.to_thread(_materialize_periodic_jobs)
                last_materialized = datetime.now().timestamp()
            await process_due_reminders()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder scheduler cycle failed")
        await asyncio.sleep(10)
