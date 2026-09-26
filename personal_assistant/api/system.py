from __future__ import annotations

import logging
import time as clock_time
from datetime import date, time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from personal_assistant.config import COOKIE_SECURE, TIMEZONE_NAME, WEB_PASSWORD
from personal_assistant.db import audit, connection
from personal_assistant.schemas import LoginRequest, ReminderSchedulesPatch, SessionBind
from personal_assistant.security import (
    SESSION_COOKIE,
    create_session,
    login_rate_limiter,
    password_matches,
    request_actor,
    require_same_origin,
)
from personal_assistant.services.domain import (
    _daily_brief_text,
    _get_setting,
    _now_local,
    _set_setting,
)

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
logger = logging.getLogger("personal_assistant")

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
def homepage() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@router.get("/app.js")
def javascript() -> FileResponse:
    return FileResponse(WEB_ROOT / "app.js", media_type="application/javascript")


@router.get("/style.css")
def stylesheet() -> FileResponse:
    return FileResponse(WEB_ROOT / "style.css", media_type="text/css")


@router.post("/api/v1/auth/login")
def login(body: LoginRequest, request: Request, response: Response) -> dict[str, bool]:
    require_same_origin(request)
    login_rate_limiter.check()
    if not WEB_PASSWORD or not password_matches(body.password):
        login_rate_limiter.failed()
        raise HTTPException(status_code=401, detail="密码不正确")
    login_rate_limiter.succeeded()
    token, expires = create_session()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max(0, expires - int(clock_time.time())),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path="/",
    )
    return {"authenticated": True}


@router.post("/api/v1/auth/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    require_same_origin(request)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )
    return {"authenticated": False}


@router.get("/api/v1/auth/me")
def auth_me(actor: str = Depends(request_actor)) -> dict[str, str]:
    return {"actor": actor}


@router.get("/api/v1/settings")
def get_settings(actor: str = Depends(request_actor)) -> dict[str, Any]:
    with connection() as conn:
        return {
            "timezone": TIMEZONE_NAME,
            "wechat_bound": bool(_get_setting(conn, "default_umo")),
            "actor": actor,
            "reminder_schedules": {
                "daily_brief_enabled": _get_setting(conn, "daily_brief_enabled", "1") == "1",
                "daily_brief_time": _get_setting(conn, "daily_brief_time", "08:00"),
                "weekly_review_enabled": _get_setting(conn, "weekly_review_enabled", "1") == "1",
                "weekly_review_weekday": int(_get_setting(conn, "weekly_review_weekday", "7")),
                "weekly_review_time": _get_setting(conn, "weekly_review_time", "20:00"),
            },
        }


@router.get("/api/v1/settings/reminder-schedules")
def get_reminder_schedules(actor: str = Depends(request_actor)) -> dict[str, Any]:
    del actor
    with connection() as conn:
        return {
            "daily_brief_enabled": _get_setting(conn, "daily_brief_enabled", "1") == "1",
            "daily_brief_time": _get_setting(conn, "daily_brief_time", "08:00"),
            "weekly_review_enabled": _get_setting(conn, "weekly_review_enabled", "1") == "1",
            "weekly_review_weekday": int(_get_setting(conn, "weekly_review_weekday", "7")),
            "weekly_review_time": _get_setting(conn, "weekly_review_time", "20:00"),
        }


@router.get("/api/v1/daily-brief")
def preview_daily_brief(
    target: date | None = Query(default=None, alias="date"),
    actor: str = Depends(request_actor),
) -> dict[str, str]:
    """Return the same composed daily push body for chat preview and manual checks."""
    del actor
    selected = target or _now_local().date()
    return {"date": selected.isoformat(), "body": _daily_brief_text(selected)}


@router.get("/api/v1/weather")
def get_weather_forecast(
    target: date | None = Query(default=None, alias="date"),
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    """Query the configured real forecast source for a specific local date."""
    del actor
    from personal_assistant.push_plugins.weather import WeatherConfigurationError, WeatherModule

    selected = target or _now_local().date()
    try:
        result = WeatherModule().forecast(selected)
    except WeatherConfigurationError as exc:
        raise HTTPException(
            status_code=503, detail="尚未配置天气地点，请在项目私有 .env 中填写天气名称和坐标。"
        ) from exc
    except Exception as exc:
        logger.warning("Weather lookup failed for %s: %s", selected, type(exc).__name__)
        raise HTTPException(status_code=502, detail="天气服务暂时无法连接，请稍后再问。") from exc
    if not result:
        raise HTTPException(status_code=502, detail="天气服务暂时没有返回这一天的预报。")
    low = result.get("temperature_min_c")
    high = result.get("temperature_max_c")
    temperature = (
        f"最低 {low:g}°C，最高 {high:g}°C"
        if isinstance(low, (int, float)) and isinstance(high, (int, float))
        else "气温数据暂缺"
    )
    rain = result.get("precipitation_probability_max")
    chance = f"，降水概率 {rain}%" if isinstance(rain, (int, float)) else ""
    result["summary"] = (
        f"【天气预报查询】{result['location']} {selected.isoformat()}：{result['condition']}，{temperature}{chance}。\n"
        f"来源：{result['source_name']}（{result['source_url']}）"
    )
    return result


@router.patch("/api/v1/settings/reminder-schedules")
def update_reminder_schedules(
    body: ReminderSchedulesPatch,
    actor: str = Depends(request_actor),
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=422, detail="没有可更新的提醒设置")
    if any(value is None for value in fields.values()):
        raise HTTPException(status_code=422, detail="提醒计划设置不能设为 null")
    with connection() as conn:
        before = {
            "daily_brief_enabled": _get_setting(conn, "daily_brief_enabled", "1") == "1",
            "daily_brief_time": _get_setting(conn, "daily_brief_time", "08:00"),
            "weekly_review_enabled": _get_setting(conn, "weekly_review_enabled", "1") == "1",
            "weekly_review_weekday": int(_get_setting(conn, "weekly_review_weekday", "7")),
            "weekly_review_time": _get_setting(conn, "weekly_review_time", "20:00"),
        }
        for key, value in fields.items():
            stored = (
                value.strftime("%H:%M")
                if isinstance(value, time)
                else str(int(value))
                if isinstance(value, bool)
                else str(value)
            )
            _set_setting(conn, key, stored)
        if any(key in fields for key in ("daily_brief_enabled", "daily_brief_time")):
            conn.execute(
                "UPDATE reminders SET status='cancelled',last_error='schedule_disabled' "
                "WHERE source_type='daily_brief' AND status='pending'"
            )
        if any(
            key in fields
            for key in ("weekly_review_enabled", "weekly_review_weekday", "weekly_review_time")
        ):
            conn.execute(
                "UPDATE reminders SET status='cancelled',last_error='schedule_disabled' "
                "WHERE source_type='weekly_review' AND status='pending'"
            )
        if fields.get("daily_brief_enabled") is False:
            conn.execute(
                "UPDATE reminders SET status='cancelled',last_error='schedule_disabled' WHERE source_type='daily_brief' AND status='pending'"
            )
        if fields.get("weekly_review_enabled") is False:
            conn.execute(
                "UPDATE reminders SET status='cancelled',last_error='schedule_disabled' WHERE source_type='weekly_review' AND status='pending'"
            )
        after = {
            "daily_brief_enabled": _get_setting(conn, "daily_brief_enabled", "1") == "1",
            "daily_brief_time": _get_setting(conn, "daily_brief_time", "08:00"),
            "weekly_review_enabled": _get_setting(conn, "weekly_review_enabled", "1") == "1",
            "weekly_review_weekday": int(_get_setting(conn, "weekly_review_weekday", "7")),
            "weekly_review_time": _get_setting(conn, "weekly_review_time", "20:00"),
        }
        audit(conn, actor, "reminder_schedules", "preferences", "update", before, after)
        return after


@router.put("/api/v1/session/bind")
def bind_session(body: SessionBind, actor: str = Depends(request_actor)) -> dict[str, bool]:
    with connection() as conn:
        old = _get_setting(conn, "default_umo")
        _set_setting(conn, "default_umo", body.umo)
        conn.execute(
            "UPDATE reminders SET recipient_umo=? WHERE recipient_umo='' AND status='pending'",
            (body.umo,),
        )
        if old != body.umo:
            audit(
                conn,
                actor,
                "session",
                "default_umo",
                "bind",
                {"umo": old} if old else None,
                {"umo": body.umo},
            )
    return {"bound": True}
