from __future__ import annotations

from typing import Any


class GlobalNewsFetchError(RuntimeError):
    pass


def fetch_yahoo_finance_news(symbol: str, timeout: int, count: int = 20) -> list[Any]:
    """Fetch global ticker news through Yahoo Finance's yfinance integration."""
    del timeout  # Ticker.get_news does not expose a timeout parameter.
    try:
        import yfinance as yf

        items = yf.Ticker(symbol).get_news(count=count, tab="news")
    except Exception as exc:
        raise GlobalNewsFetchError(str(exc)) from exc

    entries = []
    for item in items:
        content = item.get("content", item)
        provider = content.get("provider") or {}
        canonical = content.get("canonicalUrl") or {}
        click_through = content.get("clickThroughUrl") or {}
        link = canonical.get("url") or click_through.get("url")
        entries.append(
            {
                "title": content.get("title"),
                "summary": content.get("summary") or content.get("description"),
                "published": content.get("pubDate") or content.get("displayTime"),
                "link": link,
                "source": {"title": provider.get("displayName") or "Yahoo Finance"},
            }
        )
    return entries

