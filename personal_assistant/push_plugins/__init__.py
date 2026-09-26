"""Extensible content modules for scheduled assistant pushes.

Third-party modules can expose a ``personal_assistant.push_modules`` entry point
whose loaded object implements ``build(target_date) -> str | None``. A failing
optional module is skipped so the user's agenda can still be delivered.
"""

from __future__ import annotations

import logging
from datetime import date
from importlib.metadata import entry_points
from typing import Protocol

from personal_assistant.push_plugins.agenda import AgendaModule
from personal_assistant.push_plugins.news import NewsModule
from personal_assistant.push_plugins.weather import WeatherModule

logger = logging.getLogger(__name__)


class PushModule(Protocol):
    name: str

    def build(self, target: date) -> str | None: ...


def registered_modules() -> list[PushModule]:
    modules: list[PushModule] = [WeatherModule(), NewsModule(), AgendaModule()]
    try:
        extensions = entry_points(group="personal_assistant.push_modules")
    except TypeError:  # Compatibility with older importlib.metadata implementations.
        extensions = entry_points().get("personal_assistant.push_modules", [])
    for extension in extensions:
        try:
            factory = extension.load()
            modules.append(factory() if callable(factory) else factory)
        except Exception:
            logger.exception("Could not load push content module %s", extension.name)
    return modules


def render_daily_brief(target: date) -> str:
    sections: list[str] = []
    for module in registered_modules():
        try:
            content = module.build(target)
        except Exception:
            logger.exception("Push content module %s failed for %s", module.name, target)
            continue
        if content and content.strip():
            sections.append(content.strip())

    greeting = "早安"
    return f"{greeting}，{target.month}月{target.day}日的安排我帮你整理好了：\n\n" + "\n\n".join(
        sections
    )
