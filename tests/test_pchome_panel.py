import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from streamlit.testing.v1 import AppTest

from services.pchome_scraper import parse_stock


class PChomePanelTests(unittest.TestCase):
    def test_search_scores_rerun_and_failure(self):
        stock = parse_stock((Path(__file__).parent / "fixtures" / "pchome_2409.html").read_bytes(), "2409")
        with tempfile.TemporaryDirectory() as temp:
            script = (
                "from pathlib import Path\n"
                "from src.pchome_panel import render_pchome_panel\n"
                "def news(stock_symbol, limit):\n"
                "    assert stock_symbol == '2409'\n"
                "    return [{'sentiment_score': 0.5, 'importance_score': 3}]\n"
                f"render_pchome_panel(Path({temp!r}), news)\n"
            )
            with patch("src.pchome_panel.cached_stock", return_value=stock) as fetch:
                app = AppTest.from_string(script).run()
                self.assertFalse(app.exception)
                fetch.assert_not_called()
                app.button[0].click().run()
                self.assertFalse(app.exception)
                fetch.assert_called_once_with("2409")
                self.assertTrue(any(m.label == "Partial stock score" for m in app.metric))
                self.assertEqual(len(app.tabs), 4)
                app.number_input[0].set_value(0).run()
                self.assertFalse(app.exception)
                fetch.assert_called_once()
                fetch.side_effect = requests.Timeout()
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertEqual(len(app.metric), 0)


if __name__ == "__main__":
    unittest.main()
