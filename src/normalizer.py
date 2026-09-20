from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from src.models import Article, FeedSource, WatchlistStock
from src.stock_matcher import match_stock


class ArticleValidationError(ValueError):
    pass


TRACKING_PARAMETERS = {"guccounter", "soc_src", "soc_trk", "ncid"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = BeautifulSoup(html.unescape(str(value)), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _canonical_url(value: Any) -> str:
    url = html.unescape(str(value or "")).strip()
    if not url:
        raise ArticleValidationError("Article has no URL")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ArticleValidationError(f"Article has an invalid URL: {url}")
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ""))


def _published_at(entry: Any) -> str:
    raw = entry.get("published") or entry.get("updated") or entry.get("pubDate")
    if not raw:
        raise ArticleValidationError("Article has no publication time")
    try:
        raw_text = str(raw)
        if re.match(r"^\d{4}-\d{2}-\d{2}T", raw_text):
            value = datetime.fromisoformat(raw_text.replace("Z", "+00:00"))
        else:
            value = parsedate_to_datetime(raw_text)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc).replace(microsecond=0)
        return value.isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ArticleValidationError(f"Invalid publication time: {raw}") from exc


def _publisher(entry: Any) -> str:
    source = entry.get("source")
    if isinstance(source, dict):
        candidate = source.get("title") or source.get("value")
        if candidate:
            return _clean_text(candidate)
    for field in ("author", "dc_source"):
        candidate = entry.get(field)
        if candidate:
            return _clean_text(candidate)
    return "Yahoo Taiwan Stock"


def normalize_entry(
    entry: Any,
    feed_source: FeedSource,
    watchlist: list[WatchlistStock],
    collected_at: Optional[str] = None,
) -> Article:
    title = _clean_text(entry.get("title"))
    if not title:
        raise ArticleValidationError("Article has no title")
    summary = _clean_text(entry.get("summary") or entry.get("description")) or None

    stock = feed_source.stock or match_stock(title, summary, watchlist)
    return Article(
        published_at=_published_at(entry),
        source=_publisher(entry),
        category=feed_source.category,
        stock_symbol=stock.symbol if stock else None,
        company_name=stock.company_name if stock else None,
        title=title,
        summary=summary,
        url=_canonical_url(entry.get("link")),
        collected_at=collected_at or utc_now_iso(),
    )
