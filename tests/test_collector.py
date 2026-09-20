import logging
import tempfile
import unittest
from pathlib import Path

from src.collector import collect_news
from src.database import NewsDatabase
from src.models import FeedSource, WatchlistStock


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = NewsDatabase(Path(self.temp_directory.name) / "news.db")
        self.sources = [
            FeedSource("broken", "https://example.test/broken", "research"),
            FeedSource("working", "https://example.test/working", "taiwan_market"),
        ]
        self.watchlist = [WatchlistStock("2330", "台積電")]

    def tearDown(self):
        self.database.close()
        self.temp_directory.cleanup()

    @staticmethod
    def fetcher(url, timeout):
        if url.endswith("broken"):
            raise RuntimeError("network unavailable")
        return [
            {
                "title": "台積電消息",
                "summary": "Summary",
                "published": "Sun, 23 Aug 2026 07:30:00 GMT",
                "link": "https://example.test/article",
            }
        ]

    def test_continues_after_source_failure_and_counts_duplicate(self):
        logger = logging.getLogger("collector-test")
        first = collect_news(
            self.database, self.sources, self.watchlist, 1, logger, self.fetcher
        )
        second = collect_news(
            self.database, self.sources, self.watchlist, 1, logger, self.fetcher
        )

        self.assertEqual((first.fetched, first.new, first.duplicates, first.errors), (1, 1, 0, 1))
        self.assertEqual((second.fetched, second.new, second.duplicates, second.errors), (1, 0, 1, 1))
        run_count = self.database.connection.execute(
            "SELECT COUNT(*) FROM collection_runs"
        ).fetchone()[0]
        self.assertEqual(run_count, 2)


if __name__ == "__main__":
    unittest.main()

