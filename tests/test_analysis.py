import logging
import tempfile
import unittest
from pathlib import Path

from src.analysis.pipeline import analyze_pending_articles
from src.analysis.provider import NewsAnalysisProvider
from src.analysis.validation import validate_analysis
from src.database import NewsDatabase
from src.models import AIAnalysis, Article, PendingArticle


class FakeProvider(NewsAnalysisProvider):
    name = "fake"
    model = "fake-v1"

    def analyze(self, article):
        return AIAnalysis(
            stock_symbol=article.stock_symbol,
            company_name="台積電",
            ai_summary="公司提高資本支出。",
            sentiment="positive",
            sentiment_score=0.8,
            importance_score=4,
            topic="guidance",
        )


class FailingProvider(FakeProvider):
    def analyze(self, article):
        raise RuntimeError("model unavailable")


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = NewsDatabase(Path(self.temp_directory.name) / "news.db")
        self.database.insert_article(
            Article(
                published_at="2026-08-23T07:00:00Z",
                source="Publisher",
                category="stock",
                stock_symbol="2330",
                company_name=None,
                title="台積電提高資本支出",
                summary="公司宣布提高今年資本支出。",
                url="https://example.test/analysis-1",
                collected_at="2026-08-23T08:00:00Z",
            )
        )

    def tearDown(self):
        self.database.close()
        self.temp_directory.cleanup()

    def test_validates_and_calculates_stock_score(self):
        article = PendingArticle(1, "date", "2330", None, "title", None, "source")
        result = validate_analysis(
            {
                "stock_symbol": "2330.TW",
                "company_name": "台積電",
                "ai_summary": "摘要",
                "sentiment": "positive",
                "sentiment_score": 0.75,
                "importance_score": 4,
                "topic": "earnings",
            },
            article,
        )
        self.assertEqual(result.per_stock_news_score, 0.6)

    def test_rejects_inconsistent_sentiment(self):
        article = PendingArticle(1, "date", "2330", None, "title", None, "source")
        with self.assertRaises(ValueError):
            validate_analysis(
                {
                    "stock_symbol": "2330",
                    "company_name": "台積電",
                    "ai_summary": "摘要",
                    "sentiment": "positive",
                    "sentiment_score": -0.5,
                    "importance_score": 3,
                    "topic": "earnings",
                },
                article,
            )

    def test_pipeline_persists_once_and_skips_already_analyzed(self):
        first = analyze_pending_articles(
            self.database, FakeProvider(), "2330", 10, logging.getLogger("test")
        )
        second = analyze_pending_articles(
            self.database, FakeProvider(), "2330", 10, logging.getLogger("test")
        )
        self.assertEqual((first.pending, first.analyzed, first.errors), (1, 1, 0))
        self.assertEqual((second.pending, second.analyzed), (0, 0))
        row = self.database.connection.execute(
            "SELECT sentiment, sentiment_score, importance_score, per_stock_news_score "
            "FROM article_analyses"
        ).fetchone()
        self.assertEqual(row, ("positive", 0.8, 4, 0.64))

    def test_pipeline_isolates_model_errors(self):
        result = analyze_pending_articles(
            self.database, FailingProvider(), "2330", 10, logging.getLogger("test")
        )
        self.assertEqual((result.pending, result.analyzed, result.errors), (1, 0, 1))


if __name__ == "__main__":
    unittest.main()

