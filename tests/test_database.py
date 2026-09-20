import tempfile
import unittest
from pathlib import Path

from src.database import NewsDatabase
from src.models import Article


def article(url="https://example.test/1", title="Title", published="2026-08-23T07:00:00Z"):
    return Article(
        published_at=published,
        source="Publisher",
        category="research",
        stock_symbol=None,
        company_name=None,
        title=title,
        summary="Summary",
        url=url,
        collected_at="2026-08-23T08:00:00Z",
    )


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = NewsDatabase(Path(self.temp_directory.name) / "news.db")

    def tearDown(self):
        self.database.close()
        self.temp_directory.cleanup()

    def test_rejects_duplicate_url(self):
        self.assertTrue(self.database.insert_article(article()))
        self.assertFalse(self.database.insert_article(article(title="Different title")))

    def test_rejects_duplicate_title_and_publication_time(self):
        self.assertTrue(self.database.insert_article(article()))
        self.assertFalse(self.database.insert_article(article(url="https://example.test/2")))

    def test_allows_same_title_at_different_time(self):
        self.assertTrue(self.database.insert_article(article()))
        self.assertTrue(
            self.database.insert_article(
                article(url="https://example.test/2", published="2026-08-23T08:00:00Z")
            )
        )

    def test_duplicate_article_can_be_linked_to_another_stock(self):
        first = article()
        first = Article(**{**first.__dict__, "stock_symbol": "AAPL"})
        second = Article(**{**first.__dict__, "stock_symbol": "MSFT"})
        self.assertTrue(self.database.insert_article(first))
        self.assertFalse(self.database.insert_article(second))
        symbols = self.database.connection.execute(
            "SELECT stock_symbol FROM article_stocks ORDER BY stock_symbol"
        ).fetchall()
        self.assertEqual(symbols, [("AAPL",), ("MSFT",)])


if __name__ == "__main__":
    unittest.main()
