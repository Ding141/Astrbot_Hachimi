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

from assistant_pa_common.bridge import AssistantBridge, render_reminder


class PersonalAssistantPlannerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.bridge = AssistantBridge()

    @filter.llm_tool(name="reminder_create")
    async def reminder_create(self, event: AstrMessageEvent, title: str, remind_at: str, todo_id: int = 0):
        """设置一次性主动提醒。需要明确日期和时刻，不能自行猜测“晚上”等模糊时间。

        Args:
            title(string): 提醒内容
            remind_at(string): 日期和时刻，ISO 8601格式；无时区时按上海时间
            todo_id(number): 关联 Todo 编号；不关联时传0
        """
        payload = {"title": title, "remind_at": remind_at}
        if todo_id:
            payload["todo_id"] = todo_id
        result = await self.bridge.request(event, "POST", "/api/v1/reminders", payload)
        yield event.plain_result(render_reminder("create", result))

    @filter.llm_tool(name="reminder_list")
    async def reminder_list(self, event: AstrMessageEvent, status: str = "pending"):
        """查看已保存的主动提醒。

        Args:
            status(string): pending、sent、failed、uncertain、cancelled；全部时传空字符串
        """
        path = "/api/v1/reminders" + ("?" + urlencode({"status": status}) if status else "")
        result = await self.bridge.request(event, "GET", path)
        yield event.plain_result(render_reminder("list", result))

    @filter.llm_tool(name="reminder_cancel")
    async def reminder_cancel(self, event: AstrMessageEvent, reminder_id: int):
        """取消一项已确认且尚未发送的主动提醒。

        Args:
            reminder_id(number): 提醒编号
        """
        result = await self.bridge.request(event, "DELETE", f"/api/v1/reminders/{reminder_id}")
        yield event.plain_result(render_reminder("cancel", result))

    @filter.llm_tool(name="weekly_review_get")
    async def weekly_review_get(self, event: AstrMessageEvent, week_start: str = ""):
        """查看本周完成/未完成任务、下周课程与个人安排，开始一周复盘。

        Args:
            week_start(string): 本周任意一天 YYYY-MM-DD；留空时查看当前周
        """
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        selected = date.fromisoformat(week_start) if week_start else today
        monday = selected - timedelta(days=selected.weekday())
        result = await self.bridge.request(event, "GET", f"/api/v1/weekly-reviews/{monday.isoformat()}")
        yield event.plain_result(render_reminder("weekly_review", result))

    @filter.llm_tool(name="weekly_review_save")
    async def weekly_review_save(self, event: AstrMessageEvent, reflection: str, week_start: str = ""):
        """保存一周总结文字；下周具体任务请另外创建 Todo，具体时段请创建个人日程。

        Args:
            reflection(string): 用户提供的本周总结/复盘内容
            week_start(string): 本周任意一天 YYYY-MM-DD；留空时保存当前周
        """
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        selected = date.fromisoformat(week_start) if week_start else today
        monday = selected - timedelta(days=selected.weekday())
        result = await self.bridge.request(
            event, "PUT", f"/api/v1/weekly-reviews/{monday.isoformat()}", {"reflection": reflection},
        )
        if result.get("error"):
            yield event.plain_result(f"周复盘保存失败：{result['error']}")
        else:
            yield event.plain_result(f"已保存 {monday.isoformat()} 这一周的复盘。下周任务可继续告诉我创建为 Todo，带时间的安排可创建为个人日程。")

    @filter.llm_tool(name="reminder_schedules_get")
    async def reminder_schedules_get(self, event: AstrMessageEvent):
        """查看每日早报和周复盘提醒时间及启用状态。"""
        result = await self.bridge.request(event, "GET", "/api/v1/settings/reminder-schedules")
        yield event.plain_result(render_reminder("settings", result))

    @filter.llm_tool(name="reminder_schedules_set")
    async def reminder_schedules_set(
        self, event: AstrMessageEvent, daily_brief_enabled: bool | None = None,
        daily_brief_time: str = "", weekly_review_enabled: bool | None = None,
        weekly_review_weekday: int = 0, weekly_review_time: str = "",
    ):
        """调整每日早报和周复盘的启用状态与推送时间。

        Args:
            daily_brief_enabled(boolean): 是否启用每日早报
            daily_brief_time(string): 早报时间 HH:MM
            weekly_review_enabled(boolean): 是否启用周复盘提醒
            weekly_review_weekday(number): 星期几，周一1至周日7
            weekly_review_time(string): 周复盘提醒时间 HH:MM
        """
        payload = {}
        for key, value in (("daily_brief_enabled", daily_brief_enabled), ("daily_brief_time", daily_brief_time),
                           ("weekly_review_enabled", weekly_review_enabled), ("weekly_review_time", weekly_review_time)):
            if value is not None and value != "":
                payload[key] = value
        if weekly_review_weekday:
            payload["weekly_review_weekday"] = weekly_review_weekday
        result = await self.bridge.request(event, "PATCH", "/api/v1/settings/reminder-schedules", payload)
        yield event.plain_result(render_reminder("settings", result))
