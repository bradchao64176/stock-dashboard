import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from services.backtest_history import load_backtest_histories
from services.yahoo_history import download_histories
from tests.test_backtest_engine import historical_sample
from tests.test_bull_flag import universe


class StorageAndUITests(unittest.TestCase):
    def test_explicit_dates_reach_yahoo_without_batch_offset_collision(self):
        with patch("services.yahoo_history.yf.download", return_value=historical_sample()) as download:
            download_histories(["2330.TW", "5483.TWO"], batch_size=1,
                               start="2024-01-01", end="2026-01-01")
            for call in download.call_args_list:
                self.assertEqual(call.kwargs["start"], "2024-01-01")
                self.assertEqual(call.kwargs["end"], "2026-01-01")
                self.assertNotIn("period", call.kwargs)
        with patch("services.yahoo_history.yf.download", return_value=historical_sample()) as download:
            download_histories(["2330.TW"])
            self.assertEqual(download.call_args.kwargs["period"], "1y")
            self.assertNotIn("start", download.call_args.kwargs)

    def test_sqlite_cache_exact_range_refresh_and_failed_symbols(self):
        history = historical_sample()
        with tempfile.TemporaryDirectory() as temp, patch("services.backtest_history.download_histories") as download:
            download.return_value = ({"2330.TW": history}, {"missing.TWO": "offline"})
            path = Path(temp) / "prices.db"
            args = (["2330.TW", "missing.TWO"], "2024-01-01", "2026-01-01", path)
            first, errors = load_backtest_histories(*args)
            self.assertIn("missing.TWO", errors)
            download.return_value = ({}, {"missing.TWO": "offline"})
            cached, _ = load_backtest_histories(*args)
            self.assertEqual(download.call_args.args[0], ["missing.TWO"])
            pd.testing.assert_frame_equal(cached["2330.TW"], history, check_freq=False, check_dtype=False)
            download.return_value = ({"2330.TW": history}, {})
            load_backtest_histories(*args, refresh=True)
            self.assertEqual(download.call_args.args[0], ["2330.TW", "missing.TWO"])

    def test_page_scan_and_display_controls_do_not_download(self):
        with patch("src.backtest_panel.cached_universe", return_value=(universe(), {})) as roster, \
             patch("src.backtest_panel.load_backtest_histories", return_value=({"2330.TW": historical_sample()}, {})) as download:
            app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))
            app.switch_page("pages/2_下降旗形策略回測.py").run(timeout=20)
            self.assertFalse(app.exception)
            download.assert_not_called()
            roster.assert_not_called()
            app.button[0].click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            download.assert_called_once()
            self.assertGreater(len(app.get("plotly_chart")), 0)
            next(x for x in app.selectbox if x.label == "顯示 RR").set_value(3.0).run(timeout=20)
            self.assertFalse(app.exception)
            download.assert_called_once()
            next(x for x in app.selectbox if x.label == "顯示持有期").set_value(10).run(timeout=20)
            self.assertFalse(app.exception)
            download.assert_called_once()

    def test_page_no_data_does_not_make_up_results(self):
        with patch("src.backtest_panel.cached_universe", return_value=(universe(), {})), \
             patch("src.backtest_panel.load_backtest_histories", return_value=({}, {"2330.TW": "offline"})):
            app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))
            app.switch_page("pages/2_下降旗形策略回測.py").run(timeout=20)
            app.button[0].click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(len(app.get("plotly_chart")), 0)


if __name__ == "__main__":
    unittest.main()
