from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from assistant_pa_common.bridge import AssistantBridge, render_todo  # noqa: E402


class PersonalAssistantTodoPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.bridge = AssistantBridge()

    @filter.llm_tool(name="todo_create")
    async def todo_create(
        self, event: AstrMessageEvent, title: str, due_date: str = "", due_time: str = "",
        category: str = "", priority: int = 3, notes: str = "", reminders: list[str] | None = None,
        parent_id: int = 0, repeat_frequency: str = "none", repeat_weekdays: list[int] | None = None,
        repeat_start_date: str = "", repeat_end_date: str = "", reminder_times: list[str] | None = None,
        reminder_enabled: bool = True,
        repeat_month_day: int = 0, important: bool | None = None, urgent: bool | None = None,
        subtasks: list[str] | None = None,
    ):
        """创建 Todo、子任务或重复任务。只按用户明确说出的日期/时间填写。

        Args:
            title(string): 任务标题
            due_date(string): 单次截止日期 YYYY-MM-DD；重复任务可用作开始日期
            due_time(string): 截止时刻 HH:MM；只给日期时留空
            category(string): 分类
            priority(number): 1到5，默认3
            notes(string): 备注
            reminders(array[string]): 单次任务的提醒日期时间，ISO 8601格式
            parent_id(number): 子任务的父任务编号；普通任务传0
            repeat_frequency(string): none、daily、weekly或monthly
            repeat_weekdays(array[number]): 每周重复的星期，周一为1、周日为7
            repeat_start_date(string): 重复开始日期 YYYY-MM-DD；未说明时先询问
            repeat_end_date(string): 重复停止日期 YYYY-MM-DD；所有新重复任务都必须明确询问/取得
            repeat_month_day(number): 每月重复的日期1到31，仅monthly使用
            reminder_times(array[string]): 每个重复日期的提醒时刻，例如["08:00","20:00"]
            reminder_enabled(boolean): 重复任务提醒开关
            important(boolean): 是否重要；重要且紧急/重要但不紧急/不重要但紧急/都不紧急按用户语义设置
            urgent(boolean): 是否紧急；未明确时省略，系统按截止日期判断
            subtasks(array[string]): 随任务一起创建的子任务名称
        """
        repeat = repeat_frequency.lower().strip()
        if repeat not in {"none", "daily", "weekly", "monthly"}:
            yield event.plain_result("重复周期可选每日、每周或每月；请先确认一种。")
            return
        if repeat != "none":
            if not repeat_end_date:
                yield event.plain_result("重复任务需要停止日期。请告诉我重复到哪一天，再创建这组任务。")
                return
            if repeat == "monthly" and not (1 <= repeat_month_day <= 31):
                yield event.plain_result("每月重复需要确认每月几号，例如每月15日。")
                return
            days = sorted(set(repeat_weekdays or []))
            if not repeat_start_date:
                yield event.plain_result("请先确认这组任务从哪一天开始。")
                return
            start = date.fromisoformat(repeat_start_date)
            if repeat == "weekly":
                if not days:
                    yield event.plain_result("每周重复需要先确认星期几。")
                    return
            payload = {
                "title": title, "notes": notes, "category": category, "priority": priority,
                "frequency": repeat, "weekdays": days if repeat == "weekly" else [],
                "start_date": start.isoformat(), "end_date": repeat_end_date,
                "due_time": due_time or None, "reminder_enabled": bool(reminder_enabled and reminder_times),
                "reminder_times": reminder_times or [], "subtasks": subtasks or [],
            }
            if repeat == "monthly":
                payload["month_day"] = repeat_month_day
            if important is not None:
                payload["important"] = important
            if urgent is not None:
                payload["urgent"] = urgent
            result = await self.bridge.request(event, "POST", "/api/v1/todo-series", payload)
            yield event.plain_result(render_todo("create", result))
            return
        payload = {
            "title": title, "notes": notes, "category": category, "priority": priority,
            "reminders": [{"remind_at": item} for item in (reminders or [])],
            "subtasks": subtasks or [],
        }
        if important is not None:
            payload["important"] = important
        if urgent is not None:
            payload["urgent"] = urgent
        if due_date:
            payload["due_date"] = due_date
        if due_time:
            payload["due_time"] = due_time
        if parent_id:
            payload["parent_id"] = parent_id
        result = await self.bridge.request(event, "POST", "/api/v1/todos", payload)
        yield event.plain_result(render_todo("create", result))

    @filter.llm_tool(name="todo_list")
    async def todo_list(self, event: AstrMessageEvent, query: str = "", status: str = "open", due: str = ""):
        """按关键词、状态或日期查看 Todo 和子任务。

        Args:
            query(string): 标题、备注或分类关键词
            status(string): open、completed或all
            due(string): today、upcoming、overdue或空
        """
        result = await self.bridge.request(
            event, "GET", "/api/v1/todos?" + urlencode({"q": query, "status": status, "due": due}),
        )
        yield event.plain_result(render_todo("list", result))

    @filter.llm_tool(name="todo_update")
    async def todo_update(
        self, event: AstrMessageEvent, todo_id: int, title: str = "", due_date: str = "",
        due_time: str = "", category: str = "", priority: int = 0, notes: str = "",
        scope: str = "", clear_due_date: bool = False, clear_due_time: bool = False,
        clear_notes: bool = False, clear_category: bool = False, reminders: list[str] | None = None,
        important: bool | None = None, urgent: bool | None = None, subtasks: list[str] | None = None,
    ):
        """修改 Todo。重复任务必须先确认只修改本期还是整个系列。

        Args:
            todo_id(number): 已查询并确认的任务编号
            title(string): 新标题；不修改时留空
            due_date(string): 新日期 YYYY-MM-DD
            due_time(string): 新时刻 HH:MM
            category(string): 新分类
            priority(number): 新优先级；不修改时传0
            notes(string): 新备注
            scope(string): 重复任务传 occurrence 或 series；目标不明确时先追问
            clear_due_date(boolean): 清除截止日期和时刻
            clear_due_time(boolean): 只清除截止时刻
            clear_notes(boolean): 清空备注
            clear_category(boolean): 清空分类
            reminders(array[string]): 替换本任务的多个完整日期时间提醒；空数组表示清除
            important(boolean): 是否重要
            urgent(boolean): 是否紧急；省略时按截止日期自动判断
            subtasks(array[string]): 替换该任务的子任务清单；重复任务整组编辑时作为每期模板
        """
        payload = {}
        for key, value in (("title", title), ("due_date", due_date), ("due_time", due_time), ("category", category), ("notes", notes)):
            if value:
                payload[key] = value
        if priority:
            payload["priority"] = priority
        if important is not None:
            payload["important"] = important
        if urgent is not None:
            payload["urgent"] = urgent
        if subtasks is not None:
            payload["subtasks"] = subtasks
        for key, value in (("clear_due_date", clear_due_date), ("clear_due_time", clear_due_time), ("clear_notes", clear_notes), ("clear_category", clear_category)):
            if value:
                payload[key] = True
        if reminders is not None:
            payload["reminders"] = [{"remind_at": value} for value in reminders]
        path = f"/api/v1/todos/{todo_id}" + ("?" + urlencode({"scope": scope}) if scope else "")
        result = await self.bridge.request(event, "PATCH", path, payload)
        yield event.plain_result(render_todo("update", result))

    @filter.llm_tool(name="todo_complete")
    async def todo_complete(self, event: AstrMessageEvent, todo_id: int):
        """完成一项已确认的 Todo。含未完成子任务的父任务不能完成。

        Args:
            todo_id(number): 已确认的任务编号
        """
        result = await self.bridge.request(event, "POST", f"/api/v1/todos/{todo_id}/complete", {})
        yield event.plain_result(render_todo("complete", result))

    @filter.llm_tool(name="todo_delete")
    async def todo_delete(self, event: AstrMessageEvent, todo_id: int, scope: str = ""):
        """删除已确认的 Todo。重复任务需明确指定 occurrence 或 series；模糊时先追问。

        Args:
            todo_id(number): 已确认的任务编号
            scope(string): 重复任务传 occurrence 删除本期，或 series 取消未来整组
        """
        path = f"/api/v1/todos/{todo_id}" + ("?" + urlencode({"scope": scope}) if scope else "")
        result = await self.bridge.request(event, "DELETE", path)
        yield event.plain_result(render_todo("delete", result))

    @filter.llm_tool(name="todo_series_list")
    async def todo_series_list(self, event: AstrMessageEvent):
        """查看当前启用的重复任务系列及近期任务。"""
        result = await self.bridge.request(event, "GET", "/api/v1/todo-series")
        if result.get("error"):
            yield event.plain_result(f"Todo 操作失败：{result['error']}")
            return
        if not result.get("items"):
            yield event.plain_result("目前没有重复任务。")
            return
        yield event.plain_result("重复任务系列：\n" + "\n".join(render_todo("series", item) for item in result["items"]))

    @filter.llm_tool(name="todo_series_update")
    async def todo_series_update(
        self, event: AstrMessageEvent, series_id: int, title: str = "", notes: str = "",
        category: str = "", priority: int = 0, frequency: str = "",
        weekdays: list[int] | None = None, start_date: str = "", end_date: str = "",
        due_time: str = "", clear_due_time: bool = False,
        reminder_enabled: bool | None = None, reminder_times: list[str] | None = None,
        month_day: int = 0, important: bool | None = None, urgent: bool | None = None,
        subtasks: list[str] | None = None,
    ):
        """修改一个重复任务系列；整组变更前先确认用户确实想调整所有后续周期。

        Args:
            series_id(number): 从重复任务系列列表中确认的系列编号
            title(string): 新标题；不修改时留空
            notes(string): 新备注；不修改时留空
            category(string): 新分类；不修改时留空
            priority(number): 新优先级1到5；不修改时传0
            frequency(string): daily、weekly或monthly；不改周期时留空
            month_day(number): 每月重复日期1到31
            weekdays(array[number]): 新的重复星期，周一为1、周日为7
            start_date(string): 新开始日期 YYYY-MM-DD
            end_date(string): 设置停止日期 YYYY-MM-DD；修改周期规则时必须提供
            due_time(string): 每期截止时刻 HH:MM
            clear_due_time(boolean): 清除每期截止时刻
            reminder_enabled(boolean): 整组提醒开关
            reminder_times(array[string]): 每期多个提醒时刻，例如["08:00","20:00"]
            important(boolean): 是否重要
            urgent(boolean): 是否紧急
            subtasks(array[string]): 设置此系列每期复用的子任务模板
        """
        payload = {}
        for key, value in (("title", title), ("notes", notes), ("category", category),
                           ("frequency", frequency), ("start_date", start_date)):
            if value:
                payload[key] = value
        if priority:
            payload["priority"] = priority
        if important is not None:
            payload["important"] = important
        if urgent is not None:
            payload["urgent"] = urgent
        if weekdays is not None:
            payload["weekdays"] = weekdays
        if end_date:
            payload["end_date"] = end_date
        if month_day:
            payload["month_day"] = month_day
        if subtasks is not None:
            payload["subtasks"] = subtasks
        if due_time:
            payload["due_time"] = due_time
        elif clear_due_time:
            payload["due_time"] = None
        if reminder_enabled is not None:
            payload["reminder_enabled"] = reminder_enabled
        if reminder_times is not None:
            payload["reminder_times"] = reminder_times
        if not payload:
            yield event.plain_result("请说明要修改的重复任务系列内容。")
            return
        result = await self.bridge.request(event, "PATCH", f"/api/v1/todo-series/{series_id}", payload)
        yield event.plain_result(render_todo("update", result))

    @filter.llm_tool(name="todo_series_delete")
    async def todo_series_delete(self, event: AstrMessageEvent, series_id: int, confirm: bool = False):
        """取消一个重复任务系列的未来周期；执行前必须确认用户要停掉整个系列。

        Args:
            series_id(number): 从重复任务系列列表中确认的系列编号
            confirm(boolean): 用户已明确确认取消整组后传true
        """
        if not confirm:
            yield event.plain_result("取消整个重复系列会停止后续周期，请先确认是否取消。")
            return
        result = await self.bridge.request(event, "DELETE", f"/api/v1/todo-series/{series_id}")
        yield event.plain_result(render_todo("delete", result))
