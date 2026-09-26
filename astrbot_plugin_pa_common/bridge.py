from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)


class AssistantBridge:
    def __init__(self) -> None:
        self.base_url = os.environ.get("ASSISTANT_API_URL", "http://assistant-api:8000").rstrip("/")
        self.token = os.environ.get("ASSISTANT_API_TOKEN", "")

    async def request(self, event, method: str, path: str, payload=None):
        import aiohttp

        if not self.token:
            return {"error": "个人助手服务令牌未配置，请检查本项目的 AstrBot 容器配置。"}
        headers = {"Authorization": f"Bearer {self.token}"}
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if event.unified_msg_origin:
                    async with session.put(
                        f"{self.base_url}/api/v1/session/bind",
                        json={"umo": event.unified_msg_origin},
                        headers=headers,
                    ) as response:
                        if response.status >= 400:
                            return {"error": "无法绑定当前聊天会话。"}
                async with session.request(
                    method,
                    f"{self.base_url}{path}",
                    json=payload,
                    headers=headers,
                ) as response:
                    data = await response.json(content_type=None)
                    if response.status >= 400:
                        detail = data.get("detail", f"服务返回 HTTP {response.status}") if isinstance(data, dict) else str(data)
                        if isinstance(detail, list):
                            detail = "；".join(str(item.get("msg", item)) for item in detail)
                        return {"error": str(detail)}
                    return data
        except (aiohttp.ClientError, TimeoutError) as exc:
            return {"error": f"无法连接个人助手服务（{type(exc).__name__}）。"}


def _date_label(value: str | None) -> str:
    if not value:
        return "未设置截止日期"
    try:
        day = date.fromisoformat(value[:10])
        return f"{day.month}月{day.day}日"
    except ValueError:
        return value


def _todo_line(item: dict) -> str:
    identifier = f"#{item['id']} " if item.get("id") else ""
    bits = [identifier + item.get("title", "未命名任务")]
    due = _date_label(item.get("due_date"))
    if item.get("due_time"):
        due += f" {item['due_time']}"
    if item.get("due_date"):
        bits.append(f"截止：{due}")
    if item.get("category"):
        bits.append(f"分类：{item['category']}")
    if item.get("status") == "completed":
        bits.append("已完成")
    recurrence = item.get("recurrence")
    if recurrence:
        bits.append("每日重复" if recurrence.get("frequency") == "daily" else "每周重复")
    return " · ".join(bits)


def render_todo(operation: str, result: dict) -> str:
    if result.get("error"):
        return f"Todo 操作失败：{result['error']}"
    if "items" in result:
        items = result["items"]
        if not items:
            return "目前没有符合条件的待办任务。"
        lines = [f"找到 {len(items)} 项待办："]
        for item in items[:20]:
            lines.append(f"• {_todo_line(item)}")
            for child in item.get("children", []):
                marker = "✓" if child.get("status") == "completed" else "○"
                lines.append(f"  {marker} #{child['id']} {child['title']}")
            if item.get("child_count"):
                lines.append(f"  子任务进度：{item['child_done']}/{item['child_count']}")
        if len(items) > 20:
            lines.append(f"另有 {len(items) - 20} 项未显示。")
        return "\n".join(lines)
    if "instances" in result:
        days = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
        repeat = "每天" if result.get("frequency") == "daily" else "每周" + "、".join(days.get(day, "") for day in result.get("weekdays", []))
        instances = result.get("instances", [])
        following = "、".join(_date_label(item.get("due_date")) for item in instances[:4])
        if operation == "series":
            return f"重复任务系列 #{result.get('id')}「{result.get('title', '')}」：{repeat}执行；近期日期：{following or '暂无'}。"
        return f"已建立重复任务系列 #{result.get('id')}「{result.get('title', '')}」，{repeat}执行。" + (f"\n近期日期：{following}" if following else "")
    if result.get("id") and result.get("frequency") in {"daily", "weekly"}:
        days = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
        repeat = "每天" if result["frequency"] == "daily" else "每周" + "、".join(days.get(day, "") for day in result.get("weekdays", []))
        reminders = "、".join(result.get("reminder_times", [])) or "未设置"
        return f"已更新重复任务系列 #{result['id']}「{result.get('title', '')}」：{repeat}；提醒时刻：{reminders}。"
    if result.get("deleted"):
        if result.get("future_occurrences_cancelled"):
            return "已取消这个重复任务系列的未来周期，已完成历史保留。"
        scope = "整个重复系列的未来任务" if result.get("scope") == "series" else "这项任务"
        return f"已删除{scope}，历史记录仍保留。"
    if result.get("completed_at") or operation == "complete":
        return f"已完成任务「{result.get('title', '')}」。"
    if result.get("id"):
        return f"已{ {'create': '添加', 'update': '更新'}.get(operation, '保存') }待办：{_todo_line(result)}。"
    if "deleted_count" in result:
        return f"已删除 {result['deleted_count']} 项任务。"
    return "Todo 操作已完成。"


def render_courses(result: dict) -> str:
    if result.get("error"):
        return f"课表查询失败：{result['error']}"
    if "courses" in result and "date" in result:
        target = date.fromisoformat(result["date"])
        weekday = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}[target.isoweekday()]
        header = f"{target.month}月{target.day}日（{weekday}）"
        if result.get("week"):
            header += f"是第{result['week']}周"
        if result.get("term"):
            header += f"（{result['term']}）"
        courses = result.get("courses", [])
        lines = [f"{header}，今天一共有 {len(courses)} 门课："]
        for course in courses:
            lines.append("\n" + _course_line(course))
        for event in result.get("events", []):
            lines.append(f"\n• 个人安排：{event['title']}（{event.get('start_time', '')}–{event.get('end_time', '')}）")
        return "\n".join(lines)
    courses = result.get("courses", [])
    if not courses:
        return f"没有找到与“{result.get('query', '')}”匹配的课程。"
    lines = [f"找到 {len(courses)} 条课程记录："]
    weekdays = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
    for course in courses[:20]:
        period = f"第{course['start_period']}–{course.get('end_period') or course['start_period']}节" if course.get("start_period") else ""
        lines.append(f"• 课程 #{course.get('id')} · {weekdays.get(course['weekday'], '')} {period}｜{course['course_name']}｜地点：{course.get('location') or '未填'}｜教师：{course.get('teacher') or '未填'}")
    return "\n".join(lines)


def render_course_week(result: dict) -> str:
    if result.get("error"):
        return f"课表查询失败：{result['error']}"
    lines = [f"{result.get('week_start')} 至 {result.get('week_end')} 的安排："]
    if result.get("term"):
        lines.append(f"{result['term']} · 第{result.get('week', '—')}周")
    weekday_names = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
    for day in result.get("days", []):
        target = date.fromisoformat(day["date"])
        lines.append(f"\n{target.month}月{target.day}日（{weekday_names[target.isoweekday()]}）")
        courses = day.get("courses", [])
        events = day.get("events", [])
        if not courses and not events:
            lines.append("• 暂无安排")
            continue
        for course in courses:
            lines.append(_course_line(course))
        for item in events:
            clock = "–".join(value for value in (item.get("start_time"), item.get("end_time")) if value)
            lines.append(f"• {clock + '｜' if clock else ''}{item['title']}（个人安排）")
    return "\n".join(lines)


def _course_line(course: dict) -> str:
    period = f"第{course['start_period']}–{course.get('end_period') or course['start_period']}节" if course.get("start_period") else ""
    clock = f"{course['start_time']}–{course['end_time']}" if course.get("start_time") and course.get("end_time") else ""
    when = "｜".join(value for value in (period, clock) if value)
    course_id = f"（课程编号 #{course['id']}）" if course.get("id") else ""
    line = f"• {when + '｜' if when else ''}{course['course_name']}{course_id}"
    details = []
    if course.get("location"):
        details.append(f"地点：{course['location']}")
    if course.get("teacher"):
        details.append(f"老师：{course['teacher']}")
    return line + ("\n  " + "；".join(details) if details else "")


def render_reminder(operation: str, result: dict) -> str:
    if result.get("error"):
        return f"提醒操作失败：{result['error']}"
    if "items" in result:
        if not result["items"]:
            return "目前没有符合条件的提醒。"
        def local_label(value: str) -> str:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m月%d日 %H:%M")
            except ValueError:
                return value
        states = {"pending": "待发送", "sending": "发送中", "sent": "已发送", "failed": "失败", "uncertain": "结果不确定", "cancelled": "已取消"}
        return "提醒列表：\n" + "\n".join(
            f"• #{item['id']} {item['title']}｜{local_label(item['remind_at'])}｜{states.get(item['status'], item['status'])}" for item in result["items"][:20]
        )
    if result.get("cancelled"):
        return "提醒已取消。"
    if result.get("id"):
        if operation == "create":
            return f"已设置提醒「{result.get('title', '')}」，时间：{result.get('remind_at', '')}。"
        return f"提醒设置已更新：每日早报 {result.get('daily_brief_time', '')}；周复盘 {result.get('weekly_review_time', '')}。"
    if "reflection" in result:
        complete = len(result.get("completed", []))
        unfinished = len(result.get("unfinished", []))
        courses = sum(len(day.get("courses", [])) for day in result.get("next_week", []))
        events = sum(len(day.get("events", [])) for day in result.get("next_week", []))
        lines = [f"本周完成 {complete} 项任务，未完成 {unfinished} 项。下周已有 {courses} 门课和 {events} 项个人安排。"]
        if result.get("completed"):
            lines.append("\n本周已完成：")
            lines.extend(f"• {item['title']}" for item in result["completed"][:8])
        if result.get("unfinished"):
            lines.append("\n本周未完成：")
            lines.extend(f"• {item['title']}（截止 {item.get('due_date') or '未设日期'}）" for item in result["unfinished"][:8])
        for day in result.get("next_week", []):
            items = [*day.get("courses", []), *day.get("events", [])]
            if items:
                lines.append(f"\n{_date_label(day['date'])}：")
                for item in items:
                    if "course_name" in item:
                        lines.append(_course_line(item))
                    else:
                        clock = "–".join(value for value in (item.get("start_time"), item.get("end_time")) if value)
                        lines.append(f"• {clock + '｜' if clock else ''}{item['title']}（个人安排）")
        lines.append(f"\n本周复盘：{result.get('reflection') or '尚未填写'}")
        lines.append("可以继续创建下周 Todo，或把带节次/时段的事项加入个人日程。")
        return "\n".join(lines)
    if "daily_brief_enabled" in result:
        return f"提醒计划已更新。早报：{'开启' if result['daily_brief_enabled'] else '关闭'}（{result['daily_brief_time']}）；周复盘：{'开启' if result['weekly_review_enabled'] else '关闭'}（周{result['weekly_review_weekday']} {result['weekly_review_time']}）。"
    return "提醒操作已完成。"


def render_schedule_event(result: dict) -> str:
    if result.get("error"):
        return f"日程操作失败：{result['error']}"
    if result.get("deleted"):
        return "个人安排已删除。"
    if "days" in result:
        entries = [
            f"• #{item['id']} {day['date']} {item.get('start_time', '')}–{item.get('end_time', '')}｜{item['title']}"
            for day in result.get("days", []) for item in day.get("events", [])
        ]
        return "个人安排：\n" + "\n".join(entries) if entries else "这段日期内没有个人安排。"
    text = f"已保存个人安排 #{result.get('id')}「{result.get('title', '')}」，{result.get('date') or result.get('start_date', '')} {result.get('start_time', '')}–{result.get('end_time', '')}。"
    conflicts = result.get("conflicts", [])
    if conflicts:
        text += "\n时间冲突提示：" + "、".join(f"{item['date']} {item['title']}" for item in conflicts[:5])
    return text
