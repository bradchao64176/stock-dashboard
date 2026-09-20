from __future__ import annotations

import logging
from typing import Any, Callable, List

from src.database import NewsDatabase
from src.models import CollectionSummary, FeedSource, WatchlistStock
from src.normalizer import ArticleValidationError, normalize_entry, utc_now_iso
from src.sources.yahoo_tw import fetch_feed


Fetcher = Callable[[str, int], List[Any]]


def collect_news(
    database: NewsDatabase,
    sources: list[FeedSource],
    watchlist: list[WatchlistStock],
    timeout: int,
    logger: logging.Logger,
    fetcher: Fetcher = fetch_feed,
) -> CollectionSummary:
    summary = CollectionSummary()
    errors: list[str] = []
    started_at = utc_now_iso()
    run_id = database.start_run(started_at)

    for source in sources:
        try:
            entries = fetcher(source.url, timeout)
            logger.info("Fetched %d entries from %s", len(entries), source.name)
        except Exception as exc:  # Source isolation is an explicit requirement.
            summary.errors += 1
            message = f"{source.name}: {exc}"
            errors.append(message)
            logger.exception("RSS source failed: %s", source.name)
            continue

        for entry in entries:
            summary.fetched += 1
            try:
                article = normalize_entry(entry, source, watchlist)
                if database.insert_article(article):
                    summary.new += 1
                else:
                    summary.duplicates += 1
            except ArticleValidationError as exc:
                summary.errors += 1
                message = f"{source.name}: {exc}"
                errors.append(message)
                logger.warning("Skipped invalid RSS entry from %s: %s", source.name, exc)
            except Exception as exc:
                summary.errors += 1
                message = f"{source.name}: {exc}"
                errors.append(message)
                logger.exception("Could not store RSS entry from %s", source.name)

    database.finish_run(
        run_id,
        utc_now_iso(),
        summary,
        "\n".join(errors[-20:]) or None,
    )
    return summary
