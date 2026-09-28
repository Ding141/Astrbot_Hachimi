from __future__ import annotations


def test_private_api_requires_authentication(client) -> None:
    assert client.get("/api/v1/todos").status_code == 401
    assert client.get("/healthz").json() == {"status": "ok"}


def test_login_checks_origin_and_throttles_failures(client) -> None:
    wrong_origin = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://attacker.example"},
        json={"password": "wrong"},
    )
    assert wrong_origin.status_code == 403
    for _ in range(5):
        failure = client.post(
            "/api/v1/auth/login",
            json={"password": "wrong"},
        )
        assert failure.status_code == 401
    throttled = client.post(
        "/api/v1/auth/login",
        json={"password": "wrong"},
    )
    assert throttled.status_code == 429
    assert throttled.headers.get("retry-after")


def test_todo_start_end_times_and_multiple_reminders(authenticated_client) -> None:
    response = authenticated_client.post("/api/v1/todos", json={
        "title": "完成报告", "start_date": "2026-10-01", "start_time": "13:00",
        "end_date": "2026-10-01", "end_time": "16:30",
        "reminders": [
            {"remind_at": "2026-09-30T20:00"},
            {"remind_at": "2026-10-01T12:30"},
        ],
    })
    assert response.status_code == 201, response.text
    item = response.json()
    assert (item["start_date"], item["start_time"]) == ("2026-10-01", "13:00")
    assert (item["end_date"], item["end_time"]) == ("2026-10-01", "16:30")
    assert len(item["reminders"]) == 2
    assert "children" not in item

    updated = authenticated_client.patch(f"/api/v1/todos/{item['id']}", json={"end_time": "17:00"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["end_time"] == "17:00"
    completed = authenticated_client.post(f"/api/v1/todos/{item['id']}/complete")
    assert completed.status_code == 200


def test_weekly_todo_series_materializes_occurrences_and_multiple_reminders(
    authenticated_client,
) -> None:
    response = authenticated_client.post(
        "/api/v1/todo-series",
        json={
            "title": "每周提交作业",
            "frequency": "weekly",
            "weekdays": [1],
            "start_date": "2026-10-05",
            "end_date": "2026-11-02",
            "due_time": "09:00",
            "reminder_enabled": True,
            "reminder_times": ["08:00", "08:30"],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["instances"]

    result = authenticated_client.get("/api/v1/todos?q=每周提交作业").json()
    occurrence = result["items"][0]
    assert occurrence["recurrence"]["frequency"] == "weekly"
    assert len(occurrence["reminders"]) == 2

    changed = authenticated_client.patch(
        f"/api/v1/todo-series/{response.json()['id']}",
        json={
            "frequency": "monthly", "month_day": 15,
            "start_date": "2026-10-05", "end_date": "2026-12-31",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["frequency"] == "monthly"
    assert changed.json()["weekdays"] == []


def test_monthly_todo_series_clamps_month_end_with_instance_times(authenticated_client) -> None:
    response = authenticated_client.post("/api/v1/todo-series", json={
        "title": "每月整理资料", "frequency": "monthly", "month_day": 31,
        "start_date": "2026-09-30", "end_date": "2026-11-30",
        "important": True, "urgent": False, "start_time": "13:00", "end_time": "14:30",
    })
    assert response.status_code == 201, response.text
    instances = response.json()["instances"]
    dates = [item["due_date"] for item in instances]
    assert dates[:3] == ["2026-09-30", "2026-10-31", "2026-11-30"]
    assert instances[0]["important"] is True
    assert instances[0]["urgent"] is False
    assert instances[0]["start_time"] == "13:00"
    assert instances[0]["end_time"] == "14:30"
    assert "children" not in instances[0]
    automatic_urgency = authenticated_client.patch(
        f"/api/v1/todo-series/{response.json()['id']}", json={"urgent": None}
    )
    assert automatic_urgency.status_code == 200, automatic_urgency.text
    assert automatic_urgency.json()["urgent"] is None


def test_todo_quadrants_and_calendar_endpoint(authenticated_client) -> None:
    created = authenticated_client.post("/api/v1/todos", json={
        "title": "准备报告", "category": "学习", "start_date": "2026-09-29",
        "start_time": "09:00", "end_date": "2026-09-29", "end_time": "12:00",
        "important": True, "urgent": True,
    })
    assert created.status_code == 201, created.text
    assert created.json()["important"] is True
    assert created.json()["urgent"] is True
    assert created.json()["start_time"] == "09:00"
    assert created.json()["end_time"] == "12:00"
    calendar = authenticated_client.get("/api/v1/todos/calendar?from_date=2026-09-28&to_date=2026-10-04")
    assert calendar.status_code == 200, calendar.text
    assert any(item["title"] == "准备报告" for item in calendar.json()["items"])

    spanning = authenticated_client.post("/api/v1/todos", json={
        "title": "跨周任务", "start_date": "2026-09-26", "end_date": "2026-10-05",
    })
    assert spanning.status_code == 201, spanning.text
    overlap = authenticated_client.get("/api/v1/todos/calendar?from_date=2026-09-28&to_date=2026-10-04")
    assert overlap.status_code == 200, overlap.text
    assert any(item["title"] == "跨周任务" for item in overlap.json()["items"])


def test_new_recurring_todos_require_end_date(authenticated_client) -> None:
    response = authenticated_client.post("/api/v1/todo-series", json={
        "title": "无限任务", "frequency": "daily", "start_date": "2026-09-28",
    })
    assert response.status_code == 422


def test_cookie_writes_reject_cross_origin(authenticated_client) -> None:
    response = authenticated_client.post(
        "/api/v1/todos",
        headers={"Origin": "https://attacker.example"},
        json={"title": "Cross-site attempt"},
    )
    assert response.status_code == 403


def test_tailscale_forwarded_https_origin_is_accepted(client) -> None:
    response = client.post(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://assistant.tailnet.example",
            "X-Forwarded-Host": "assistant.tailnet.example",
            "X-Forwarded-Proto": "https",
        },
        json={"password": "isolated-test-password"},
    )
    assert response.status_code == 200


def test_security_headers_and_module_assets(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in page.headers["content-security-policy"]
    module = client.get("/assets/core.js")
    assert module.status_code == 200
    assert "export const appState" not in module.text
    assert "export const $" in module.text


def test_static_modules_escape_dynamic_content() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "web" / "js"
    todos_module = (root / "todos.js").read_text(encoding="utf-8")
    timetable_module = (root / "timetable.js").read_text(encoding="utf-8")
    assert "${escapeHtml(item.title)}" in todos_module
    assert "${escapeHtml(item.course_name)}" in timetable_module
