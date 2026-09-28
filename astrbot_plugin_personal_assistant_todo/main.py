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
        self, event: AstrMessageEvent, title: str, start_date: str = "", start_time: str = "",
        end_date: str = "", end_time: str = "",
        category: str = "", priority: int = 3, notes: str = "", reminders: list[str] | None = None,
        repeat_frequency: str = "none", repeat_weekdays: list[int] | None = None,
        repeat_start_date: str = "", repeat_end_date: str = "", reminder_times: list[str] | None = None,
        reminder_enabled: bool = True,
        repeat_month_day: int = 0, important: bool | None = None, urgent: bool | None = None,
    ):
        """创建一项待办。支持开始与结束时间、单次或多次提醒，以及每日/每周/每月重复。

        Args:
            title(string): 任务标题
            start_date(string): 单次任务开始日期 YYYY-MM-DD
            start_time(string): 单次任务或重复任务每一期的开始时刻 HH:MM
            end_date(string): 单次任务结束日期 YYYY-MM-DD
            end_time(string): 单次任务或重复任务每一期的结束时刻 HH:MM
            category(string): 分类
            priority(number): 1到5，默认3
            notes(string): 备注
            reminders(array[string]): 单次任务的提醒日期时间，ISO 8601格式
            repeat_frequency(string): none、daily、weekly或monthly
            repeat_weekdays(array[number]): 每周重复的星期，周一为1、周日为7
            repeat_start_date(string): 重复开始日期 YYYY-MM-DD；未说明时先询问
            repeat_end_date(string): 重复停止日期 YYYY-MM-DD；所有新重复任务都必须明确询问/取得
            repeat_month_day(number): 每月重复的日期1到31，仅monthly使用
            reminder_times(array[string]): 每个重复日期的提醒时刻，例如["08:00","20:00"]
            reminder_enabled(boolean): 重复任务提醒开关
            important(boolean): 是否重要；重要且紧急/重要但不紧急/不重要但紧急/都不紧急按用户语义设置
            urgent(boolean): 是否紧急；未明确时省略，系统按结束日期判断
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
            try:
                start = date.fromisoformat(repeat_start_date)
                stop = date.fromisoformat(repeat_end_date)
            except ValueError:
                yield event.plain_result("重复任务的开始和停止日期请使用 YYYY-MM-DD 格式。")
                return
            if stop < start:
                yield event.plain_result("重复任务的停止日期不能早于开始日期。")
                return
            if repeat == "weekly":
                if not days:
                    yield event.plain_result("每周重复需要先确认星期几。")
                    return
            payload = {
                "title": title, "notes": notes, "category": category, "priority": priority,
                "frequency": repeat, "weekdays": days if repeat == "weekly" else [],
                "start_date": start.isoformat(), "end_date": repeat_end_date,
                "start_time": start_time or None, "end_time": end_time or None,
                "reminder_enabled": bool(reminder_enabled and reminder_times),
                "reminder_times": reminder_times or [],
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
        }
        if important is not None:
            payload["important"] = important
        if urgent is not None:
            payload["urgent"] = urgent
        for key, value in (("start_date", start_date), ("start_time", start_time), ("end_date", end_date), ("end_time", end_time)):
            if value:
                payload[key] = value
        result = await self.bridge.request(event, "POST", "/api/v1/todos", payload)
        yield event.plain_result(render_todo("create", result))

    @filter.llm_tool(name="todo_list")
    async def todo_list(self, event: AstrMessageEvent, query: str = "", status: str = "open", due: str = ""):
        """按关键词、状态或日期查看待办。

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
        self, event: AstrMessageEvent, todo_id: int, title: str = "", start_date: str = "",
        start_time: str = "", end_date: str = "", end_time: str = "",
        category: str = "", priority: int = 0, notes: str = "",
        scope: str = "", clear_start_date: bool = False, clear_start_time: bool = False,
        clear_end_date: bool = False, clear_end_time: bool = False,
        clear_notes: bool = False, clear_category: bool = False, reminders: list[str] | None = None,
        important: bool | None = None, urgent: bool | None = None,
    ):
        """修改 Todo。重复任务必须先确认只修改本期还是整个系列。

        Args:
            todo_id(number): 已查询并确认的任务编号
            title(string): 新标题；不修改时留空
            start_date(string): 开始日期 YYYY-MM-DD
            start_time(string): 开始时刻 HH:MM
            end_date(string): 结束日期 YYYY-MM-DD
            end_time(string): 结束时刻 HH:MM
            category(string): 新分类
            priority(number): 新优先级；不修改时传0
            notes(string): 新备注
            scope(string): 重复任务传 occurrence 或 series；目标不明确时先追问
            clear_start_date(boolean): 清除开始日期和时刻
            clear_start_time(boolean): 只清除开始时刻
            clear_end_date(boolean): 清除结束日期和时刻
            clear_end_time(boolean): 只清除结束时刻
            clear_notes(boolean): 清空备注
            clear_category(boolean): 清空分类
            reminders(array[string]): 替换本任务的多个完整日期时间提醒；空数组表示清除
            important(boolean): 是否重要
            urgent(boolean): 是否紧急；省略时按结束日期自动判断
        """
        payload = {}
        for key, value in (("title", title), ("start_date", start_date), ("start_time", start_time),
                           ("end_date", end_date), ("end_time", end_time), ("category", category), ("notes", notes)):
            if value:
                payload[key] = value
        if priority:
            payload["priority"] = priority
        if important is not None:
            payload["important"] = important
        if urgent is not None:
            payload["urgent"] = urgent
        for key, value in (("clear_start_date", clear_start_date), ("clear_start_time", clear_start_time),
                           ("clear_end_date", clear_end_date), ("clear_end_time", clear_end_time),
                           ("clear_notes", clear_notes), ("clear_category", clear_category)):
            if value:
                payload[key] = True
        if reminders is not None:
            payload["reminders"] = [{"remind_at": value} for value in reminders]
        path = f"/api/v1/todos/{todo_id}" + ("?" + urlencode({"scope": scope}) if scope else "")
        result = await self.bridge.request(event, "PATCH", path, payload)
        yield event.plain_result(render_todo("update", result))

    @filter.llm_tool(name="todo_complete")
    async def todo_complete(self, event: AstrMessageEvent, todo_id: int):
        """完成一项已确认的待办。

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
        start_time: str = "", end_time: str = "", clear_start_time: bool = False,
        clear_end_time: bool = False,
        reminder_enabled: bool | None = None, reminder_times: list[str] | None = None,
        month_day: int = 0, important: bool | None = None, urgent: bool | None = None,
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
            start_time(string): 每期开始时刻 HH:MM
            end_time(string): 每期结束时刻 HH:MM
            clear_start_time(boolean): 清除每期开始时刻
            clear_end_time(boolean): 清除每期结束时刻
            reminder_enabled(boolean): 整组提醒开关
            reminder_times(array[string]): 每期多个提醒时刻，例如["08:00","20:00"]
            important(boolean): 是否重要
            urgent(boolean): 是否紧急
        """
        payload = {}
        normalized_frequency = frequency.strip().lower()
        if normalized_frequency and normalized_frequency not in {"daily", "weekly", "monthly"}:
            yield event.plain_result("重复周期可选每日、每周或每月。")
            return
        recurrence_fields_supplied = bool(normalized_frequency or start_date or month_day or weekdays is not None)
        if recurrence_fields_supplied and not end_date:
            yield event.plain_result("修改重复规则前需要确认新的停止日期。")
            return
        if normalized_frequency == "weekly" and not weekdays:
            yield event.plain_result("修改为每周重复时，请提供星期几（周一为1，周日为7）。")
            return
        if normalized_frequency == "monthly" and not (1 <= month_day <= 31):
            yield event.plain_result("修改为每月重复时，请提供每月日期1到31。")
            return
        if normalized_frequency in {"daily", "monthly"} and weekdays:
            yield event.plain_result("每日或每月重复不能同时指定星期。")
            return
        if normalized_frequency in {"daily", "weekly"} and month_day:
            yield event.plain_result("每日或每周重复不能同时指定每月日期。")
            return
        for key, value in (("title", title), ("notes", notes), ("category", category),
                           ("frequency", normalized_frequency), ("start_date", start_date)):
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
        if start_time:
            payload["start_time"] = start_time
        elif clear_start_time:
            payload["start_time"] = None
        if end_time:
            payload["end_time"] = end_time
        elif clear_end_time:
            payload["end_time"] = None
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
