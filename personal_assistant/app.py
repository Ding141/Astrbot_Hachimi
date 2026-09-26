from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from personal_assistant.api import courses, exports, reminders, reviews, schedule, system, todos
from personal_assistant.config import validate_secrets
from personal_assistant.db import initialize_database
from personal_assistant.reminders import scheduler_loop
from personal_assistant.services import domain as _domain

# Backwards-compatible exports used by existing scheduler and push modules.
WEEKDAY_ZH = _domain.WEEKDAY_ZH
_add_reminder = _domain._add_reminder
_cancel_unsent_reminders = _domain._cancel_unsent_reminders
_clock_minutes = _domain._clock_minutes
_course_payload = _domain._course_payload
_course_query_for_date = _domain._course_query_for_date
_daily_brief_text = _domain._daily_brief_text
_display_course = _domain._display_course
_event_dates = _domain._event_dates
_event_matches = _domain._event_matches
_event_payload = _domain._event_payload
_events_for_date = _domain._events_for_date
_get_setting = _domain._get_setting
_materialize_todo_series = _domain._materialize_todo_series
_normalize_datetime = _domain._normalize_datetime
_now_local = _domain._now_local
_queue_scheduled_reminder = _domain._queue_scheduled_reminder
_schedule_conflicts = _domain._schedule_conflicts
_series_matches = _domain._series_matches
_set_setting = _domain._set_setting
_todo_payload = _domain._todo_payload
_weekly_review_text = _domain._weekly_review_text

logger = logging.getLogger("personal_assistant")


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_secrets()
    initialize_database()
    scheduler = asyncio.create_task(scheduler_loop(), name="reminder-scheduler")
    try:
        yield
    finally:
        scheduler.cancel()
        try:
            await scheduler
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    application = FastAPI(title="个人 AI 助手", version="0.5.0", lifespan=lifespan)
    for router in (
        system.router,
        todos.router,
        reminders.router,
        courses.router,
        schedule.router,
        reviews.router,
        exports.router,
    ):
        application.include_router(router)

    # Static feature modules are same-origin assets; keeping this mount narrow
    # prevents the application from exposing files outside web/js.
    application.mount("/assets", StaticFiles(directory=system.WEB_ROOT / "js"), name="assets")

    @application.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        if (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").casefold() == "https"
        ):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    return application


app = create_app()
