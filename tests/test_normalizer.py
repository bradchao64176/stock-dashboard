import unittest

from src.models import FeedSource, WatchlistStock
from src.normalizer import ArticleValidationError, normalize_entry


class NormalizerTests(unittest.TestCase):
    def setUp(self):
        self.stock = WatchlistStock("2330", "台積電", ("TSMC",))
        self.source = FeedSource("Taiwan market", "https://example.test/rss", "taiwan_market")

    def test_normalizes_html_timestamp_url_and_stock(self):
        article = normalize_entry(
            {
                "title": " 台積電   法說會 ",
                "summary": "<p>營收&nbsp;<strong>成長</strong></p>",
                "published": "Sun, 23 Aug 2026 07:30:00 GMT",
                "link": "https://example.test/news/1?utm_source=rss&item=2#top",
                "source": {"title": "中央社"},
            },
            self.source,
            [self.stock],
            collected_at="2026-08-23T08:00:00Z",
        )

        self.assertEqual(article.title, "台積電 法說會")
        self.assertEqual(article.summary, "營收 成長")
        self.assertEqual(article.published_at, "2026-08-23T07:30:00Z")
        self.assertEqual(article.url, "https://example.test/news/1?item=2")
        self.assertEqual(article.stock_symbol, "2330")
        self.assertEqual(article.source, "中央社")

    def test_stock_feed_context_takes_priority(self):
        stock_source = FeedSource("stock", "https://example.test/rss", "stock", self.stock)
        article = normalize_entry(
            {
                "title": "半導體產業消息",
                "published": "Sun, 23 Aug 2026 07:30:00 GMT",
                "link": "https://example.test/news/2",
            },
            stock_source,
            [self.stock],
        )
        self.assertEqual(article.stock_symbol, "2330")
        self.assertEqual(article.company_name, "台積電")

    def test_rejects_missing_publication_time(self):
        with self.assertRaises(ArticleValidationError):
            normalize_entry(
                {"title": "News", "link": "https://example.test/news/3"},
                self.source,
                [self.stock],
            )


if __name__ == "__main__":
    unittest.main()

