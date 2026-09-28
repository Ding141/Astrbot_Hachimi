from __future__ import annotations

from datetime import date


class AgendaModule:
    name = "agenda"

    def build(self, target: date) -> str:
        # Imported at call time to keep this module usable while app.py is loading.
        from personal_assistant.app import (
            WEEKDAY_ZH,
            _course_query_for_date,
            _display_course,
            _events_for_date,
        )
        from personal_assistant.db import connection

        with connection() as conn:
            day = _course_query_for_date(conn, target)
            events = _events_for_date(conn, target)
            todos = conn.execute(
                "SELECT title,start_time,due_time FROM todos WHERE status='open' AND deleted_at IS NULL "
                "AND COALESCE(due_date,start_date)=? ORDER BY COALESCE(start_time,due_time),id",
                (target.isoformat(),),
            ).fetchall()
            overdue = conn.execute(
                "SELECT title,start_date,due_date FROM todos WHERE status='open' AND deleted_at IS NULL "
                "AND COALESCE(due_date,start_date)<? ORDER BY COALESCE(due_date,start_date),due_time LIMIT 20",
                (target.isoformat(),),
            ).fetchall()

        context = f"{WEEKDAY_ZH[target.isoweekday()]}"
        if day.get("week"):
            context += f" · 第 {day['week']} 周"
        if day.get("term"):
            context += f" · {day['term']}"
        lines = [f"📅 今日安排（{context}）"]
        lines.append(f"课程 · {len(day['courses'])} 门")
        lines.extend(_display_course(course) for course in day["courses"])
        if not day["courses"]:
            lines.append("• 今天没有课程，留些时间给自己。")

        lines.append(f"\n🧩 个人安排 · {len(events)} 项")
        for event in events:
            clock = f"{event.get('start_time') or ''}–{event.get('end_time') or ''}".strip("–")
            lines.append(f"• {clock + '｜' if clock else ''}{event['title']}")
        if not events:
            lines.append("• 目前没有个人日程。")

        lines.append(f"\n✅ 今天到期 · {len(todos)} 项")
        lines.extend(
            f"• {row['title']}{' · ' + (row['start_time'] or row['due_time']) if row['start_time'] or row['due_time'] else ''}" for row in todos
        )
        if not todos:
            lines.append("• 暂无到期任务。")
        if overdue:
            lines.append(f"\n⏳ 逾期任务 · {len(overdue)} 项")
            lines.extend(f"• {row['title']} · 截止 {row['due_date'] or row['start_date']}" for row in overdue)
        return "\n".join(lines)
