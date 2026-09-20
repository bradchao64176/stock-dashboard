import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.models import FeedSource, WatchlistStock
from src.normalizer import normalize_entry
from src.sources.yahoo_global import fetch_yahoo_finance_news


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def get_news(self, count, tab):
        return [
            {
                "content": {
                    "title": f"News for {self.symbol}",
                    "summary": "Company guidance increased.",
                    "pubDate": "2026-08-23T08:35:00Z",
                    "provider": {"displayName": "Publisher"},
                    "canonicalUrl": {"url": "https://example.test/global-news"},
                }
            }
        ]


class YahooGlobalTests(unittest.TestCase):
    def test_maps_global_yahoo_news_to_normalized_article(self):
        fake_yfinance = SimpleNamespace(Ticker=FakeTicker)
        with patch.dict(sys.modules, {"yfinance": fake_yfinance}):
            entries = fetch_yahoo_finance_news("AAPL", 20)

        stock = WatchlistStock("AAPL", "")
        article = normalize_entry(
            entries[0],
            FeedSource("Yahoo global", "AAPL", "stock", stock),
            [],
        )
        self.assertEqual(article.stock_symbol, "AAPL")
        self.assertEqual(article.published_at, "2026-08-23T08:35:00Z")
        self.assertEqual(article.source, "Publisher")


if __name__ == "__main__":
    unittest.main()
