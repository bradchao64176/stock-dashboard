from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import FeedSource, WatchlistStock


class ConfigurationError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            value = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration root must be an object: {path}")
    return value


def load_watchlist(path: Path) -> list[WatchlistStock]:
    config = _read_json(path)
    rows = config.get("stocks")
    if not isinstance(rows, list) or not rows:
        raise ConfigurationError("watchlist.json must contain a non-empty 'stocks' list")

    stocks: list[WatchlistStock] = []
    symbols: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ConfigurationError(f"Watchlist item {index + 1} must be an object")
        symbol = str(row.get("symbol", "")).strip()
        company_name = str(row.get("company_name", "")).strip()
        aliases = row.get("aliases", [])
        if not symbol or not company_name:
            raise ConfigurationError(f"Watchlist item {index + 1} needs symbol and company_name")
        if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
            raise ConfigurationError(f"Aliases for {symbol} must be a list of strings")
        if symbol in symbols:
            raise ConfigurationError(f"Duplicate watchlist symbol: {symbol}")
        symbols.add(symbol)
        stocks.append(
            WatchlistStock(
                symbol=symbol,
                company_name=company_name,
                aliases=tuple(alias.strip() for alias in aliases if alias.strip()),
            )
        )
    return stocks


def load_source_config(path: Path, stocks: list[WatchlistStock]) -> tuple[list[FeedSource], int]:
    config = _read_json(path)
    rows = config.get("sources")
    template = config.get("stock_feed_url")
    timeout = config.get("request_timeout_seconds", 20)
    if not isinstance(rows, list):
        raise ConfigurationError("rss_sources.json must contain a 'sources' list")
    if not isinstance(template, str) or "{symbol}" not in template:
        raise ConfigurationError("stock_feed_url must contain the {symbol} placeholder")
    if not isinstance(timeout, int) or timeout <= 0:
        raise ConfigurationError("request_timeout_seconds must be a positive integer")

    # Stock feeds run first so stock metadata is retained if an article is also
    # present in a broader category feed.
    sources = [
        FeedSource(
            name=f"Yahoo Taiwan Stock - {stock.symbol} {stock.company_name}",
            url=template.format(symbol=stock.symbol),
            category="stock",
            stock=stock,
        )
        for stock in stocks
    ]
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ConfigurationError(f"RSS source {index + 1} must be an object")
        if not row.get("enabled", True):
            continue
        name = str(row.get("name", "")).strip()
        url = str(row.get("url", "")).strip()
        category = str(row.get("category", "")).strip()
        if not name or not url or not category:
            raise ConfigurationError(f"RSS source {index + 1} needs name, url, and category")
        sources.append(FeedSource(name=name, url=url, category=category))
    return sources, timeout
