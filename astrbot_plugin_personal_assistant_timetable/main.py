from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from assistant_pa_common.bridge import (  # noqa: E402
    AssistantBridge,
    render_course_week,
    render_courses,
    render_schedule_event,
)


def _message_text(event) -> str:
    message = getattr(event, "message_str", "")
    if callable(message):
        try:
            message = message()
        except Exception:
            message = ""
    if not message and hasattr(event, "get_message_str"):
        try:
            message = event.get_message_str()
        except Exception:
            message = ""
    return str(message or "").strip().replace("。", "").replace("！", "").replace("!", "")


def _user_confirmed(event, phrase: str, identifier: int | None = None) -> bool:
    normalized = _message_text(event)
    allowed = {
        "reminder": {"确认", "确认执行", "确认批量提醒", "按预览设置", "按预览执行", "就按这个设置"},
    }
    if phrase == "delete" and identifier is not None:
        return normalized in {
            f"确认删除 #{identifier}", f"确认删除课程 #{identifier}",
            f"确认删除{identifier}", f"确认删除课程{identifier}",
        }
    return normalized in allowed.get(phrase, set())


class PersonalAssistantTimetablePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.bridge = AssistantBridge()

    @filter.llm_tool(name="course_query")
    async def course_query(self, event: AstrMessageEvent, course_date: str = "", weekday: int = 0):
        """查询指定日期或最近一次指定星期的课程和个人安排；不指定时查询今天。

        Args:
            course_date(string): 日期 YYYY-MM-DD
            weekday(number): 星期几，周一为1、周日为7
        """
        params = {"date": course_date} if course_date else {"weekday": weekday} if weekday else {
            "date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        }
        result = await self.bridge.request(event, "GET", "/api/v1/courses?" + urlencode(params))
        yield event.plain_result(render_courses(result))

    @filter.llm_tool(name="course_week")
    async def course_week(self, event: AstrMessageEvent, week_start: str = ""):
        """查看某周的完整课程与个人日程；日期不必是周一，系统会自动对齐。

        Args:
            week_start(string): 这一周任意一天的日期 YYYY-MM-DD；留空表示本周
        """
        params = {"week_start": week_start} if week_start else {}
        result = await self.bridge.request(event, "GET", "/api/v1/courses/week" + ("?" + urlencode(params) if params else ""))
        yield event.plain_result(render_course_week(result))

    @filter.llm_tool(name="course_search")
    async def course_search(self, event: AstrMessageEvent, query: str):
        """按课程名、教师或地点查找课程。

        Args:
            query(string): 搜索关键词
        """
        result = await self.bridge.request(event, "GET", "/api/v1/courses/search?" + urlencode({"q": query}))
        yield event.plain_result(render_courses(result))

    @filter.llm_tool(name="course_reminder_set")
    async def course_reminder_set(self, event: AstrMessageEvent, course_id: int, enabled: bool, lead_minutes: int = 10):
        """启用/关闭单门课程的课前提醒，并设置提前分钟数。

        Args:
            course_id(number): 已查到并确认的课程编号
            enabled(boolean): 是否开启
            lead_minutes(number): 提前分钟数，默认10
        """
        result = await self.bridge.request(
            event, "PATCH", f"/api/v1/courses/{course_id}",
            {"reminder_enabled": enabled, "reminder_lead_minutes": lead_minutes},
        )
        if result.get("error"):
            yield event.plain_result(f"课程提醒设置失败：{result['error']}")
        else:
            state = "已开启" if result.get("reminder_enabled") else "已关闭"
            yield event.plain_result(f"「{result.get('course_name', '课程')}」课前提醒{state}，提前 {result.get('reminder_lead_minutes', lead_minutes)} 分钟。")

    @filter.llm_tool(name="course_reminder_batch_preview")
    async def course_reminder_batch_preview(
        self, event: AstrMessageEvent, start_periods: list[int] | None = None,
        course_ids: list[int] | None = None, term_id: int = 0, enabled: bool = True,
        lead_minutes: int = 10,
    ):
        """批量调整课程提醒的第一步：只预览，不会改动数据。必须先把匹配清单和提前时间告知用户，并等待用户在下一条消息中明确回复“确认”后，才能调用 course_reminder_batch_apply。

        Args:
            start_periods(array[number]): 按开始节次筛选，例如[3,8]；不能把上课中包含该节的课算进来
            course_ids(array[number]): 可选的课程编号筛选；提供时按这些编号预览
            term_id(number): 学期编号；留空时使用当前有效学期
            enabled(boolean): 是否开启提醒，默认true
            lead_minutes(number): 提前分钟数，0到180
        """
        result = await self.bridge.request(
            event, "POST", "/api/v1/courses/reminders/preview",
            {"start_periods": start_periods or [], "course_ids": course_ids or [],
             "term_id": term_id or None, "enabled": enabled, "lead_minutes": lead_minutes,
             "umo": event.unified_msg_origin or ""},
        )
        if result.get("error"):
            yield event.plain_result(f"課前提醒预览没成功：{result['error']}")
            return
        lines = [f"我找到 {result['count']} 门课（{result['term']}），准备{'开启' if enabled else '关闭'}提醒，提前 {lead_minutes} 分钟："]
        for item in result["courses"][:20]:
            period = f"第{item.get('start_period')}节" if item.get("start_period") else "未录入节次"
            lines.append(f"• #{item['id']} {item['course_name']}｜周{item['weekday']}｜{period}")
        if result["count"] > 20:
            lines.append(f"另有 {result['count'] - 20} 门未展开。")
        lines.append(f"预览有效至 {result['expires_at']}。确认后请回复“确认”，我再执行；目前还没有修改。")
        lines.append(f"预览编号：{result['preview_id']}")
        yield event.plain_result("\n".join(lines))

    @filter.llm_tool(name="course_reminder_batch_apply")
    async def course_reminder_batch_apply(self, event: AstrMessageEvent, preview_id: str = ""):
        """执行上一条消息中已展示且用户在当前消息明确确认的课程提醒预览。绝不能在预览的同一轮调用，也不能把用户最初的请求当作确认。

        Args:
            preview_id(string): 预览编号；若当前微信会话只有一项最新预览，可留空
        """
        if not _user_confirmed(event, "reminder"):
            yield event.plain_result("请先查看上条列出的课程和提醒时间；如果确定，单独回复“确认”后我再执行。")
            return
        result = await self.bridge.request(
            event, "POST", "/api/v1/courses/reminders/apply",
            {"preview_id": preview_id, "umo": event.unified_msg_origin or "", "confirmed": True},
        )
        if result.get("error"):
            yield event.plain_result(f"批量提醒没有执行：{result['error']}")
        else:
            yield event.plain_result(f"完成啦，已为 {result['updated_count']} 门课{'开启' if result['enabled'] else '关闭'}课前提醒，提前 {result['lead_minutes']} 分钟。🔔")

    @filter.llm_tool(name="course_update")
    async def course_update(
        self, event: AstrMessageEvent, course_id: int, course_name: str | None = None, weekday: int = 0,
        start_period: int = 0, end_period: int = 0, start_time: str | None = None, end_time: str | None = None,
        weeks: list[int] | None = None, week_parity: str | None = None, location: str | None = None,
        teacher: str | None = None, notes: str | None = None,
    ):
        """修改已查询确认的整门课程；仅修改明确提供的字段，清空地点/老师/备注时传空字符串。

        Args:
            course_id(number): 课程编号
            course_name(string): 新课程名
            weekday(number): 星期1到7
            start_period(number): 开始节次
            end_period(number): 结束节次
            start_time(string): 开始时刻HH:MM
            end_time(string): 结束时刻HH:MM
            weeks(array[number]): 上课周次；空列表表示每周按单双周规则
            week_parity(string): all、odd或even
            location(string): 地点；传空字符串可清除
            teacher(string): 老师；传空字符串可清除
            notes(string): 备注；传空字符串可清除
        """
        payload = {}
        for key, value in (("course_name", course_name), ("weekday", weekday or None),
                           ("start_period", start_period or None), ("end_period", end_period or None),
                           ("start_time", start_time), ("end_time", end_time), ("week_parity", week_parity)):
            if value is not None and value != "":
                payload[key] = value
        for key, value in (("weeks", weeks), ("location", location), ("teacher", teacher), ("notes", notes)):
            if value is not None:
                payload[key] = value
        if not payload:
            yield event.plain_result("告诉我需要改哪项课程信息吧。")
            return
        result = await self.bridge.request(event, "PATCH", f"/api/v1/courses/{course_id}", payload)
        if result.get("error"):
            yield event.plain_result(f"课程修改失败：{result['error']}")
        else:
            yield event.plain_result(f"已更新「{result['course_name']}」的课程信息。🗓️")

    @filter.llm_tool(name="course_create")
    async def course_create(
        self, event: AstrMessageEvent, term_id: int, course_name: str, weekday: int,
        start_period: int = 0, end_period: int = 0, start_time: str | None = None, end_time: str | None = None,
        weeks: list[int] | None = None, week_parity: str = "all", location: str = "",
        teacher: str = "", notes: str = "",
    ):
        """向已导入学期添加一门课程。先查学期，再确认用户明确提供的课程日、时间和周次，不推测缺失信息。

        Args:
            term_id(number): 从学期列表确认的学期编号
            course_name(string): 课程名称
            weekday(number): 星期1到7
            start_period(number): 开始节次；和结束节次同时填写
            end_period(number): 结束节次
            start_time(string): 可选开始时间HH:MM；使用时也要提供end_time
            end_time(string): 可选结束时间HH:MM
            weeks(array[number]): 上课周次；空列表表示按单双周规则
            week_parity(string): all、odd或even
            location(string): 教室或地点
            teacher(string): 教师
            notes(string): 备注
        """
        if bool(start_period) != bool(end_period) or bool(start_time) != bool(end_time):
            yield event.plain_result("开始和结束节次、或开始和结束时间都需要成对提供。")
            return
        if not (start_period and end_period) and not (start_time and end_time):
            yield event.plain_result("请补充课程的节次范围，或明确开始和结束时刻。")
            return
        payload = {"term_id": term_id, "course_name": course_name, "weekday": weekday,
                   "week_parity": week_parity, "location": location, "teacher": teacher, "notes": notes,
                   "weeks": weeks or []}
        if start_period:
            payload.update({"start_period": start_period, "end_period": end_period})
        if start_time:
            payload.update({"start_time": start_time, "end_time": end_time})
        result = await self.bridge.request(event, "POST", "/api/v1/courses", payload)
        if result.get("error"):
            yield event.plain_result(f"课程没有添加成功：{result['error']}")
        else:
            yield event.plain_result(f"已把「{result['course_name']}」加入课表（课程编号 #{result['id']}）。📚")

    @filter.llm_tool(name="course_occurrence_update")
    async def course_occurrence_update(
        self, event: AstrMessageEvent, course_id: int, occurrence_date: str, action: str = "override",
        start_period: int = 0, end_period: int = 0, start_time: str | None = None, end_time: str | None = None,
        location: str | None = None, teacher: str | None = None, notes: str | None = None,
    ):
        """调整指定日期的一次课程，或标记该日停课；不会修改整学期课程规则。

        Args:
            course_id(number): 课程编号
            occurrence_date(string): 日期YYYY-MM-DD
            action(string): override调整本次信息；cancelled表示仅此日停课
            start_period(number): 调课后的开始节次
            end_period(number): 调课后的结束节次
            start_time(string): 调课后的开始时间HH:MM，与结束时间同时填写
            end_time(string): 调课后的结束时间HH:MM
            location(string): 临时地点
            teacher(string): 临时教师
            notes(string): 本次备注
        """
        if action not in {"override", "cancelled"}:
            yield event.plain_result("action只支持override或cancelled。")
            return
        payload = {"action": action}
        for key, value in (("start_period", start_period), ("end_period", end_period),
                           ("start_time", start_time), ("end_time", end_time),
                           ("location", location), ("teacher", teacher), ("notes", notes)):
            if key in {"location", "teacher", "notes"} and value is not None:
                payload[key] = value
            elif key not in {"location", "teacher", "notes"} and value:
                payload[key] = value
        if bool(start_period) != bool(end_period) or bool(start_time) != bool(end_time):
            yield event.plain_result("开始和结束节次或时间需要成对填写。")
            return
        result = await self.bridge.request(event, "PUT", f"/api/v1/courses/{course_id}/occurrences/{occurrence_date}", payload)
        if result.get("error"):
            yield event.plain_result(f"本次课程调整失败：{result['error']}")
        elif action == "cancelled":
            yield event.plain_result(f"已将课程 #{course_id} 在 {occurrence_date} 标记为停课。")
        else:
            yield event.plain_result(f"已调整课程 #{course_id} 在 {occurrence_date} 的本次安排。")

    @filter.llm_tool(name="course_occurrence_restore")
    async def course_occurrence_restore(self, event: AstrMessageEvent, course_id: int, occurrence_date: str):
        """撤销指定日期的一次课程调整，让它恢复为学期课表规则。"""
        result = await self.bridge.request(event, "DELETE", f"/api/v1/courses/{course_id}/occurrences/{occurrence_date}")
        yield event.plain_result("已恢复这一天的原课表。" if not result.get("error") else f"恢复失败：{result['error']}")

    @filter.llm_tool(name="course_delete")
    async def course_delete(self, event: AstrMessageEvent, course_id: int):
        """删除一整门课程和它的所有排课；先查询目标，之后必须展示课程名并等待用户在下一条消息明确回复“确认删除”。

        Args:
            course_id(number): 已查到的课程编号
        """
        if not _user_confirmed(event, "delete", course_id):
            course = await self.bridge.request(event, "GET", f"/api/v1/courses/{course_id}")
            if course.get("error"):
                yield event.plain_result(f"课程查询失败：{course['error']}")
            else:
                yield event.plain_result(f"删除整门课会移除「{course['course_name']}」整个学期的排课。若确认，请单独回复“确认删除 #{course_id}”。")
            return
        result = await self.bridge.request(event, "DELETE", f"/api/v1/courses/{course_id}?confirm=true")
        yield event.plain_result(f"已删除课程「{result.get('course_name', '')}」。" if not result.get("error") else f"课程删除失败：{result['error']}")

    @filter.llm_tool(name="schedule_event_create")
    async def schedule_event_create(
        self, event: AstrMessageEvent, title: str, event_date: str = "", start_period: int = 0,
        end_period: int = 0, start_time: str = "", end_time: str = "", frequency: str = "once",
        weekdays: list[int] | None = None, start_date: str = "", end_date: str = "", notes: str = "",
    ):
        """在课表中添加单次或每周重复的个人安排；时间冲突会提示但仍保存。

        Args:
            title(string): 安排名称
            event_date(string): 单次安排日期 YYYY-MM-DD
            start_period(number): 开始节次1到14；和结束节次同时填写
            end_period(number): 结束节次1到14
            start_time(string): 可选具体开始时间 HH:MM；使用具体时间时不要传节次
            end_time(string): 可选具体结束时间 HH:MM
            frequency(string): once或weekly
            weekdays(array[number]): 每周安排的星期，周一为1、周日为7
            start_date(string): 每周安排从哪天开始 YYYY-MM-DD
            end_date(string): 每周安排停止日期，创建时必须明确提供
            notes(string): 备注
        """
        payload = {"title": title, "notes": notes, "frequency": frequency}
        if frequency == "weekly":
            if not start_date or not weekdays:
                yield event.plain_result("每周安排需要确认开始日期和星期几。")
                return
            if not end_date:
                yield event.plain_result("每周安排需要明确停止日期。请告诉我重复到哪一天，再保存。")
                return
            payload.update({"start_date": start_date, "end_date": end_date, "weekdays": weekdays})
        else:
            if not event_date:
                yield event.plain_result("单次安排需要先确认具体日期。")
                return
            payload["event_date"] = event_date
        if start_period or end_period:
            if not start_period or not end_period:
                yield event.plain_result("请同时提供开始节次和结束节次。")
                return
            payload.update({"start_period": start_period, "end_period": end_period})
        elif start_time and end_time:
            payload.update({"start_time": start_time, "end_time": end_time})
        else:
            yield event.plain_result("请确认安排的节次范围，或明确开始和结束时间。")
            return
        result = await self.bridge.request(event, "POST", "/api/v1/schedule-events", payload)
        yield event.plain_result(render_schedule_event(result))

    @filter.llm_tool(name="schedule_event_list")
    async def schedule_event_list(self, event: AstrMessageEvent, from_date: str = "", to_date: str = ""):
        """查看一段日期内的个人安排。

        Args:
            from_date(string): 起始日期 YYYY-MM-DD，默认今天
            to_date(string): 结束日期 YYYY-MM-DD，默认未来两周
        """
        params = {}
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        result = await self.bridge.request(event, "GET", "/api/v1/schedule-events" + ("?" + urlencode(params) if params else ""))
        yield event.plain_result(render_schedule_event(result))

    @filter.llm_tool(name="schedule_event_update")
    async def schedule_event_update(
        self, event: AstrMessageEvent, event_id: int, title: str = "", event_date: str = "",
        start_period: int = 0, end_period: int = 0, notes: str = "", frequency: str = "",
        start_date: str = "", end_date: str = "", weekdays: list[int] | None = None,
        start_time: str = "", end_time: str = "",
    ):
        """修改一项已确认的个人安排。

        Args:
            event_id(number): 已查询并确认的日程编号
            title(string): 新标题
            event_date(string): 新日期 YYYY-MM-DD
            start_period(number): 新开始节次
            end_period(number): 新结束节次
            notes(string): 新备注
            frequency(string): once或weekly；不改重复规则时留空
            start_date(string): 每周重复开始日期 YYYY-MM-DD
            end_date(string): 设置或调整重复规则时的停止日期 YYYY-MM-DD
            weekdays(array[number]): 新重复星期；周一为1、周日为7
            start_time(string): 改用具体时间时的开始时刻 HH:MM
            end_time(string): 改用具体时间时的结束时刻 HH:MM
        """
        payload = {key: value for key, value in (("title", title), ("event_date", event_date), ("start_period", start_period or None), ("end_period", end_period or None), ("notes", notes)) if value is not None and value != ""}
        if frequency:
            payload["frequency"] = frequency
        if (frequency == "weekly" or start_date or weekdays is not None) and not end_date:
            yield event.plain_result("修改每周重复规则需要明确停止日期，请先告诉我重复到哪一天。")
            return
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        if weekdays is not None:
            payload["weekdays"] = weekdays
        if start_time:
            payload["start_time"] = start_time
        if end_time:
            payload["end_time"] = end_time
        result = await self.bridge.request(event, "PATCH", f"/api/v1/schedule-events/{event_id}", payload)
        yield event.plain_result(render_schedule_event(result))

    @filter.llm_tool(name="schedule_event_delete")
    async def schedule_event_delete(self, event: AstrMessageEvent, event_id: int):
        """删除一项已确认的个人安排。

        Args:
            event_id(number): 已查询并确认的日程编号
        """
        result = await self.bridge.request(event, "DELETE", f"/api/v1/schedule-events/{event_id}")
        yield event.plain_result(render_schedule_event(result))
