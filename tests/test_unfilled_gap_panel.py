import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from tests.test_bull_flag import universe
from tests.test_unfilled_gap import unfilled_history
from services.backtest_history import load_backtest_histories


class UnfilledPanelTests(unittest.TestCase):
    def test_actions_cache_does_not_reuse_actionless_snapshot(self):
        ordinary = unfilled_history()
        actions = ordinary.assign(Dividends=0.0)
        with tempfile.TemporaryDirectory() as temp, patch("services.backtest_history.download_histories") as download:
            download.side_effect = [({"2330.TW": ordinary}, {}), ({"2330.TW": actions}, {})]
            args = (["2330.TW"], "2025-01-01", "2026-01-01", Path(temp) / "prices.db")
            load_backtest_histories(*args)
            data, _ = load_backtest_histories(*args, actions=True)
            self.assertIn("Dividends", data["2330.TW"])
            cached, _ = load_backtest_histories(*args, actions=True)
            self.assertIn("Dividends", cached["2330.TW"])
            self.assertEqual(download.call_count, 2)

    def test_defaults_scan_and_status_filter_no_redownload(self):
        with patch("src.unfilled_gap_panel.cached_universe", return_value=(universe(), {})), \
             patch("src.unfilled_gap_panel.load_backtest_histories", return_value=({"2330.TW": unfilled_history()}, {})) as download:
            app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))
            app.switch_page("pages/4_多方未回補缺口選股.py").run(timeout=20)
            self.assertFalse(app.exception)
            for name in ("Close > MA20", "MA20 > MA60", "MA20 Rising"):
                self.assertTrue(next(c for c in app.checkbox if c.label == name).value)
            self.assertEqual(next(c for c in app.selectbox if c.label == "Trend Evaluation").value, "GAP_DAY_AND_CURRENT")
            download.assert_not_called()
            app.button[0].click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(len(app.get("plotly_chart")), 1)
            app.multiselect[0].set_value(["FILLED"]).run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("plotly_chart")), 0)
            download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
