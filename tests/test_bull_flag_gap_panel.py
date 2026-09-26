import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.test_bull_flag import universe
from tests.test_bull_flag_gap import gap_history


class GapPanelTests(unittest.TestCase):
    def test_scan_filters_chart_and_navigation_without_redownload(self):
        with patch("src.bull_flag_gap_panel.cached_universe", return_value=(universe(), {})) as roster, \
             patch("src.bull_flag_gap_panel.cached_histories", return_value=({"2330.TW": gap_history([120, 118.1])}, {})) as download:
            app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))
            app.switch_page("pages/3_下降旗形多方缺口突破.py").run(timeout=20)
            self.assertFalse(app.exception)
            download.assert_not_called()
            self.assertEqual(next(s for s in app.selectbox if s.label.startswith("Gap Lookback")).value, 20)
            app.button[0].click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(len(app.get("plotly_chart")), 1)
            download.assert_called_once_with(("2330.TW",), include_actions=True)
            next(c for c in app.checkbox if c.label == "Only Untouched Gaps").set_value(True).run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("plotly_chart")), 0)
            next(c for c in app.checkbox if c.label == "Only Untouched Gaps").set_value(False).run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("plotly_chart")), 1)
            download.assert_called_once()
            roster.assert_called_once()

    def test_empty_results_and_source_errors_are_real(self):
        with patch("src.bull_flag_gap_panel.cached_universe", return_value=(universe(), {"TPEx": "offline"})), \
             patch("src.bull_flag_gap_panel.cached_histories", return_value=({}, {"2330.TW": "offline"})):
            app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))
            app.switch_page("pages/3_下降旗形多方缺口突破.py").run(timeout=20)
            app.button[0].click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertTrue(app.warning)
            self.assertEqual(len(app.get("plotly_chart")), 0)


if __name__ == "__main__":
    unittest.main()
