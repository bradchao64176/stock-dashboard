from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collector import collect_news  # noqa: E402
from src.database import NewsDatabase  # noqa: E402
from src.logging_config import configure_logging  # noqa: E402
from src.models import FeedSource, WatchlistStock  # noqa: E402
from src.sources.yahoo_global import fetch_yahoo_finance_news  # noqa: E402


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Collect Yahoo Taiwan Stock RSS news for one stock code."
    )
    parser.add_argument(
        "symbol",
        help="Stock code or ticker, for example 2330, 2330.TW, or AAPL",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    ticker = arguments.symbol.strip().upper()
    is_taiwan_stock = ticker.endswith((".TW", ".TWO")) or ticker.isdigit()
    symbol = ticker.split(".", 1)[0] if is_taiwan_stock else ticker
    if not symbol:
        print("News Collection Failed: stock symbol cannot be empty", file=sys.stderr)
        return 2

    logger = configure_logging(PROJECT_ROOT / "logs" / "collector.log")
    database = None
    try:
        stock = WatchlistStock(symbol=symbol, company_name="")
        if is_taiwan_stock:
            source = FeedSource(
                name=f"Yahoo Taiwan Stock - {symbol}",
                url=f"https://tw.stock.yahoo.com/rss?s={quote(symbol, safe='')}",
                category="stock",
                stock=stock,
            )
            fetcher = None
        else:
            source = FeedSource(
                name=f"Yahoo Finance Global - {symbol}",
                url=symbol,
                category="stock",
                stock=stock,
            )
            fetcher = fetch_yahoo_finance_news
        database = NewsDatabase(PROJECT_ROOT / "data" / "stock_news.db")
        collect_arguments = dict(
            database=database,
            sources=[source],
            watchlist=[],
            timeout=20,
            logger=logger,
        )
        if fetcher is not None:
            collect_arguments["fetcher"] = fetcher
        summary = collect_news(**collect_arguments)
    except (OSError, RuntimeError) as exc:
        logger.exception("Collector stopped because of a fatal error")
        print(f"News Collection Failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.close()

    print("News Collection Complete")
    print(f"Stock: {symbol}")
    print()
    print(f"Fetched: {summary.fetched}")
    print(f"New: {summary.new}")
    print(f"Duplicates: {summary.duplicates}")
    print(f"Errors: {summary.errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
