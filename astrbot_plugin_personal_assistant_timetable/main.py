from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from assistant_pa_common.bridge import AssistantBridge, render_course_week, render_courses, render_schedule_event


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
            end_date(string): 每周安排结束日期，可留空表示长期
            notes(string): 备注
        """
        payload = {"title": title, "notes": notes, "frequency": frequency}
        if frequency == "weekly":
            if not start_date or not weekdays:
                yield event.plain_result("每周安排需要确认开始日期和星期几。")
                return
            payload.update({"start_date": start_date, "end_date": end_date or None, "weekdays": weekdays})
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
        start_time: str = "", end_time: str = "", clear_end_date: bool = False,
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
            end_date(string): 每周重复结束日期 YYYY-MM-DD
            weekdays(array[number]): 新重复星期；周一为1、周日为7
            start_time(string): 改用具体时间时的开始时刻 HH:MM
            end_time(string): 改用具体时间时的结束时刻 HH:MM
            clear_end_date(boolean): 清除每周重复的结束日期
        """
        payload = {key: value for key, value in (("title", title), ("event_date", event_date), ("start_period", start_period or None), ("end_period", end_period or None), ("notes", notes)) if value is not None and value != ""}
        if frequency:
            payload["frequency"] = frequency
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        elif clear_end_date:
            payload["end_date"] = None
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
