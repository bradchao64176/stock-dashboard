import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from services.backtest_history import load_incremental_histories, load_backtest_histories
from src.impulse_macd import ImpulseConfig, smma, crossover, calculate_impulse, historical_cross_events, scan_impulse_universe


def prices(n=250):
    x = np.arange(n)
    close = 100 + x * .06 + 12 * np.sin(x / 11.)
    return pd.DataFrame(dict(Open=close, High=close + .5, Low=close - .5, Close=close, Volume=1000.), index=pd.bdate_range("2024-01-01", periods=n))


STOCK = dict(ticker="2330.TW", stock_code="2330", stock_name="Test", market="TWSE")


class ImpulseTests(unittest.TestCase):
    def test_smma_sma_seed_and_recursion(self):
        actual = smma(pd.Series([1., 2., 6., 9., np.nan, 3., 6., 9.]), 3)
        np.testing.assert_allclose(actual, [np.nan, np.nan, 3., 5., np.nan, np.nan, np.nan, 6.], equal_nan=True)

    def test_manual_formula_and_warmup(self):
        raw = prices()
        data = calculate_impulse(raw)
        src = (raw.High + raw.Low + raw.Close) / 3
        first = src.ewm(span=34, adjust=False).mean()
        np.testing.assert_allclose(data.Impulse_ZLEMA, 2 * first - first.ewm(span=34, adjust=False).mean())
        self.assertTrue(data.Impulse_MACD.iloc[:33].isna().all())
        self.assertTrue(data.Impulse_Signal.iloc[:41].isna().all())
        self.assertTrue(np.isfinite(data.Impulse_Signal.iloc[41]))
        np.testing.assert_allclose(data.Impulse_Histogram, data.Impulse_MACD - data.Impulse_Signal, equal_nan=True)

    def test_true_cross_zero_plateau_no_repeat(self):
        macd = pd.Series([-2., 0., 0., 0., 0., 1.])
        signal = pd.Series([-1., -1., -.5, -.1, 0., 0.])
        self.assertEqual(crossover(macd, signal).tolist(), [False, True, False, False, False, True])

    def test_future_does_not_change_indicators_or_events(self):
        raw = prices()
        full = calculate_impulse(raw)
        short = calculate_impulse(raw.iloc[:180])
        pd.testing.assert_frame_equal(full.iloc[:180], short)
        self.assertEqual([e for e in historical_cross_events(full, STOCK) if e["signal_index"] < 180], historical_cross_events(short, STOCK))

    def test_missing_bar_resets_warmup(self):
        raw = prices()
        raw.iloc[100, raw.columns.get_loc("Close")] = np.nan
        data = calculate_impulse(raw)
        self.assertTrue(data.Impulse_Signal.iloc[100:142].isna().all())
        self.assertFalse(data.golden_cross.iloc[100:143].any())

    def test_positive_and_trend_filters(self):
        data = calculate_impulse(prices())
        events = historical_cross_events(data, STOCK)
        self.assertGreater(len(events), 0)
        positive = historical_cross_events(data, STOCK, ImpulseConfig(require_positive_impulse=True))
        self.assertTrue(all(e["Impulse_MACD"] > 0 for e in positive))
        trend = historical_cross_events(data, STOCK, ImpulseConfig(require_close_above_ma20=True, require_ma20_above_ma60=True))
        self.assertTrue(all(e["signal_close"] > e["MA20"] > e["MA60"] for e in trend))

    def test_lookback_boundaries_and_latest_event(self):
        raw = prices()
        index = historical_cross_events(calculate_impulse(raw), STOCK)[-1]["signal_index"]
        universe = pd.DataFrame([STOCK])
        for extra, lookback, expected in [(0, 0, 1), (1, 0, 0), (4, 5, 1), (5, 5, 0)]:
            result = scan_impulse_universe(universe, {STOCK["ticker"]: raw.iloc[:index + extra + 1]}, ImpulseConfig(cross_lookback_days=lookback))
            self.assertEqual(len(result["candidates"]), expected)
            if expected:
                self.assertEqual(result["candidates"].iloc[0].trading_days_since_cross, extra)

    def test_bad_history_does_not_abort_universe(self):
        result = scan_impulse_universe(pd.DataFrame([STOCK]), {STOCK["ticker"]: prices(10)})
        self.assertEqual(result["stats"]["skipped"], 1)
        self.assertTrue(result["candidates"].empty)

    def test_cache_only_missing_tail_and_upsert(self):
        raw = prices(10)
        start, middle, end = raw.index[0], raw.index[5], raw.index[-1] + pd.Timedelta(days=1)
        with tempfile.TemporaryDirectory() as temp, patch("services.backtest_history.download_histories") as download:
            download.side_effect = [({"2330.TW": raw.iloc[:5]}, {}), ({"2330.TW": raw.iloc[5:]}, {})]
            path = Path(temp) / "existing.db"
            load_incremental_histories(["2330.TW"], start, middle, path)
            data, errors = load_incremental_histories(["2330.TW"], start, end, path)
            self.assertFalse(errors)
            self.assertEqual(len(data["2330.TW"]), 10)
            self.assertEqual(download.call_args.kwargs["start"], str(middle.date()))
            load_incremental_histories(["2330.TW"], start, end, path)
            self.assertEqual(download.call_count, 2)

    def test_reuses_existing_action_snapshot_without_network(self):
        raw = prices(10)
        with tempfile.TemporaryDirectory() as temp, patch("services.backtest_history.download_histories", return_value=({"2330.TW": raw}, {})) as download:
            path = Path(temp) / "shared.db"
            load_backtest_histories(["2330.TW"], "2024-01-01", "2024-01-15", path, actions=True)
            cached, errors = load_incremental_histories(["2330.TW"], "2024-01-01", "2024-01-15", path)
            self.assertEqual(len(cached["2330.TW"]), 10)
            self.assertFalse(errors)
            download.assert_called_once()

    def test_failed_fetch_is_retried_and_not_marked_covered(self):
        with tempfile.TemporaryDirectory() as temp, patch("services.backtest_history.download_histories", return_value=({}, {"2330.TW": "offline"})) as download:
            for _ in range(2):
                data, errors = load_incremental_histories(["2330.TW"], "2024-01-01", "2024-02-01", Path(temp) / "cache.db")
                self.assertFalse(data)
                self.assertIn("2330.TW", errors)
            self.assertEqual(download.call_count, 2)

    def test_ui_scans_through_service_and_filter_does_not_download(self):
        raw = prices()
        last = historical_cross_events(calculate_impulse(raw), STOCK)[-1]["signal_index"]
        with patch("src.impulse_panel.cached_universe", return_value=(pd.DataFrame([STOCK]), {})), \
             patch("src.impulse_panel.load_incremental_histories", return_value=({"2330.TW": raw.iloc[:last+1]}, {})) as service:
            app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))
            app.switch_page("pages/5_Impulse_MACD.py").run(timeout=20)
            self.assertFalse(app.exception)
            service.assert_not_called()
            app.button[0].click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(len(app.get("plotly_chart")), 1)
            app.checkbox[-1].check().run(timeout=20)
            service.assert_called_once()


if __name__ == "__main__":
    unittest.main()
