from __future__ import annotations

from pathlib import Path
import sys
from urllib.parse import urlencode

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from assistant_pa_common.bridge import AssistantBridge


class PersonalAssistantPushPlugin(Star):
    """Chat entry point for the separately composed push-content modules."""

    def __init__(self, context: Context):
        super().__init__(context)
        self.bridge = AssistantBridge()

    @filter.llm_tool(name="daily_brief_preview")
    async def daily_brief_preview(self, event: AstrMessageEvent, target_date: str = ""):
        """预览某日将发送的早报，包含已启用的日程、天气和新闻内容模块。

        Args:
            target_date(string): 日期 YYYY-MM-DD；留空表示今天
        """
        query = urlencode({"date": target_date}) if target_date else ""
        result = await self.bridge.request(event, "GET", "/api/v1/daily-brief" + (f"?{query}" if query else ""))
        if result.get("error"):
            yield event.plain_result(f"早报预览失败：{result['error']}")
            return
        yield event.plain_result(result.get("body", "目前没有可展示的早报内容。"))

    @filter.llm_tool(name="weather_today")
    async def weather_today(self, event: AstrMessageEvent, target_date: str = ""):
        """查询本地配置地点的真实天气预报。用户询问今天或某日天气时必须调用此工具，不要猜测天气。
        最终回复必须保留“天气预报查询”标记和工具返回的来源名称、链接；不能把工具数据说成模型自身实时联网所得。

        Args:
            target_date(string): 日期 YYYY-MM-DD；留空表示今天
        """
        query = urlencode({"date": target_date}) if target_date else ""
        result = await self.bridge.request(event, "GET", "/api/v1/weather" + (f"?{query}" if query else ""))
        if result.get("error"):
            yield event.plain_result(f"天气暂时没查到：{result['error']}")
            return
        yield event.plain_result(result.get("summary", "天气服务没有返回可用预报。"))
