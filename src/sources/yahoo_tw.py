from __future__ import annotations

from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import feedparser


USER_AGENT = "StockNewsCollector/1.0 (+personal research; Yahoo Taiwan RSS)"


class FeedFetchError(RuntimeError):
    pass


def fetch_feed(url: str, timeout: int) -> list[Any]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read()
    except (HTTPError, URLError, OSError) as exc:
        raise FeedFetchError(str(exc)) from exc

    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise FeedFetchError(f"Malformed RSS: {parsed.bozo_exception}")
    return list(parsed.entries)
