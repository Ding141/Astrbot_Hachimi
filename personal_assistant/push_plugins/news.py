from __future__ import annotations

import html
import logging
import os
import re
from datetime import date
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

logger = logging.getLogger(__name__)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(value))).strip()


class NewsModule:
    name = "news"

    def build(self, target: date) -> str | None:
        del target  # Feeds contain their own publication times and are fetched at send time.
        feeds = [
            value.strip() for value in os.getenv("NEWS_RSS_URLS", "").split(",") if value.strip()
        ]
        if not feeds:
            return None
        headlines: list[tuple[str, str]] = []
        for url in feeds[:4]:
            try:
                request = Request(url, headers={"User-Agent": "PersonalAssistant/0.5 (RSS reader)"})
                with urlopen(request, timeout=3) as response:
                    root = ElementTree.fromstring(response.read())
            except Exception:
                logger.exception("Could not read configured news feed %s", url)
                continue
            items = root.findall(".//item")
            for item in items:
                text = (
                    _clean("".join(item.find("title").itertext()))
                    if item.find("title") is not None
                    else ""
                )
                article_url = _clean(item.findtext("link") or "")
                if text and all(existing[0] != text for existing in headlines):
                    headlines.append((text, article_url or url))
                if len(headlines) >= 4:
                    break
            atom_entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for item in atom_entries if len(headlines) < 4 else []:
                title = item.find("{http://www.w3.org/2005/Atom}title")
                text = _clean("".join(title.itertext())) if title is not None else ""
                link = item.find("{http://www.w3.org/2005/Atom}link")
                article_url = (link.get("href", "") if link is not None else "").strip()
                if text and all(existing[0] != text for existing in headlines):
                    headlines.append((text, article_url or url))
                if len(headlines) >= 4:
                    break
            if len(headlines) >= 4:
                break
        if not headlines:
            return None
        lines = []
        for headline, article_url in headlines:
            domain = urlparse(article_url).netloc or "新闻 RSS"
            lines.extend((f"• {headline}", f"  来源：{domain}（{article_url}）"))
        return "📰 今日新闻速览（联网抓取）\n" + "\n".join(lines)
