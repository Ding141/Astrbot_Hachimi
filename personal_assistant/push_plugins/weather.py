from __future__ import annotations

import json
import os
from datetime import date
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WEATHER_CODES = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "有雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    56: "冻毛毛雨",
    57: "冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷雨",
    96: "雷雨伴冰雹",
    99: "强雷雨伴冰雹",
}


class WeatherConfigurationError(ValueError):
    """Raised when a deployment has not supplied its private weather location."""


class WeatherModule:
    name = "weather"

    def forecast(self, target: date) -> dict | None:
        latitude = os.getenv("WEATHER_LATITUDE", "").strip()
        longitude = os.getenv("WEATHER_LONGITUDE", "").strip()
        location = os.getenv("WEATHER_LOCATION_NAME", "").strip()
        if not latitude or not longitude or not location:
            raise WeatherConfigurationError(
                "Weather location is not configured. Set WEATHER_LOCATION_NAME, "
                "WEATHER_LATITUDE, and WEATHER_LONGITUDE in the private .env file."
            )
        query = urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": os.getenv("TIMEZONE", "Asia/Shanghai"),
                "start_date": target.isoformat(),
                "end_date": target.isoformat(),
            }
        )
        source_url = f"https://api.open-meteo.com/v1/forecast?{query}"
        request = Request(source_url, headers={"User-Agent": "PersonalAssistant/0.5"})
        with urlopen(request, timeout=3) as response:
            report = json.loads(response.read().decode("utf-8"))
        daily = report.get("daily") or {}
        if not daily.get("time"):
            return None
        code = int((daily.get("weather_code") or [0])[0])
        high = (daily.get("temperature_2m_max") or [None])[0]
        low = (daily.get("temperature_2m_min") or [None])[0]
        rain = (daily.get("precipitation_probability_max") or [None])[0]
        return {
            "location": location,
            "date": daily["time"][0],
            "condition": WEATHER_CODES.get(code, "天气情况"),
            "temperature_min_c": low,
            "temperature_max_c": high,
            "precipitation_probability_max": rain,
            "source_name": "Open-Meteo 天气预报 API",
            "source_url": source_url,
            "source_docs_url": "https://open-meteo.com/en/docs",
        }

    def build(self, target: date) -> str | None:
        if not all(
            os.getenv(key, "").strip()
            for key in ("WEATHER_LOCATION_NAME", "WEATHER_LATITUDE", "WEATHER_LONGITUDE")
        ):
            return None
        result = self.forecast(target)
        if not result:
            return None
        low = result.get("temperature_min_c")
        high = result.get("temperature_max_c")
        temperature = (
            f"最低 {low:g}°，最高 {high:g}°"
            if isinstance(low, (int, float)) and isinstance(high, (int, float))
            else "气温数据暂缺"
        )
        rain = result.get("precipitation_probability_max")
        chance = f"，降水概率 {rain}%" if isinstance(rain, (int, float)) else ""
        return (
            f"🌤️ 天气 · {result['location']}：{result['condition']}，{temperature}{chance}。\n"
            f"来源：{result['source_name']}（{result['source_url']}）"
        )
