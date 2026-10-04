import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.test_bull_flag import synthetic, universe
from src.bull_flag_panel import load_news_scores


class BullFlagPanelTests(unittest.TestCase):
    def test_scan_filter_and_detail_do_not_download_again(self):
        with patch("src.bull_flag_panel.cached_universe", return_value=(universe(), {})) as roster, \
             patch("src.bull_flag_panel.cached_histories", return_value=({"2330.TW": synthetic()}, {})) as download, \
             patch("src.bull_flag_panel.load_news_scores", return_value={"2330": 75}):
            app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))
            app.switch_page("pages/1_台股下降旗形選股.py").run()
            self.assertFalse(app.exception)
            roster.assert_not_called()
            download.assert_not_called()
            # Preserve original scanner assertions with the new optional post-filter disabled.
            app.session_state["liquidity_bear_flag_enabled"] = False
            app.button[0].click().run()
            self.assertFalse(app.exception)
            download.assert_called_once()
            self.assertEqual(len(app.tabs), 2)
            self.assertEqual(len(app.get("plotly_chart")), 2)
            app.slider[0].set_value(100).run()
            self.assertFalse(app.exception)
            download.assert_called_once()
            app.slider[0].set_value(60).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("plotly_chart")), 2)
            download.assert_called_once()

    def test_empty_and_partial_market_results(self):
        with patch("src.bull_flag_panel.cached_universe", return_value=(universe(), {"TPEx": "offline"})), \
             patch("src.bull_flag_panel.cached_histories", return_value=({}, {"2330.TW": "offline"})), \
             patch("src.bull_flag_panel.load_news_scores", return_value={}):
            app = AppTest.from_string("from src.bull_flag_panel import render_bull_flag_panel\nrender_bull_flag_panel()").run()
            # Preserve original scanner assertions with the new optional post-filter disabled.
            app.session_state["liquidity_bear_flag_enabled"] = False
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.warning)
            self.assertEqual(len(app.tabs), 2)

    def test_news_latest_analysis_per_article_and_stock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "news.db"
            self.assertEqual(load_news_scores(path, ["2330"]), {})
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript("""
                    CREATE TABLE articles (id INTEGER, published_at TEXT);
                    CREATE TABLE article_stocks (article_id INTEGER, stock_symbol TEXT);
                    CREATE TABLE article_analyses (id INTEGER, article_id INTEGER,
                        stock_symbol TEXT, sentiment_score REAL, importance_score REAL);
                    INSERT INTO articles VALUES (1, '2026-01-01'), (2, '2026-01-02');
                    INSERT INTO article_stocks VALUES (1, '2330'), (2, '2330'), (1, '5483');
                    INSERT INTO article_analyses VALUES
                        (1, 1, '2330', -1, 5), (2, 1, '2330', 1, 3),
                        (3, 2, '2330', -1, 1), (4, 1, '5483', -1, 5);
                """)
            scores = load_news_scores(path, ["2330", "5483", "9999"])
            self.assertEqual(scores, {"2330": 75, "5483": 0})


if __name__ == "__main__":
    unittest.main()
