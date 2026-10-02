from dataclasses import replace
from pathlib import Path
import copy
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from services.entry_timing_config import EntryTimingConfig
from services.entry_timing_service import (calculate_entry_analysis, calculate_histogram_direction,
    calculate_atr, calculate_risk_targets, calculate_reference_stop, analyze_candidates)
from src.impulse_macd import calculate_impulse, ImpulseConfig
from src.strong_impulse import scan_strong_universe
from tests.test_impulse_macd import prices, STOCK


def fixture(price=102., age=2):
    data = calculate_impulse(prices(180))
    data.loc[:, ["Open", "High", "Low", "Close", "Volume"]] = [100., 108., 95., 100., 1000.]
    data.loc[:, ["MA20", "MA60", "ma20_slope_pct", "Impulse_MACD", "Impulse_Signal", "Impulse_Histogram", "volume_ratio_20", "ATR"]] = [100., 90., .02, 2., 1., 1., 2., 4.]
    data.loc[data.index[-2], "Impulse_Histogram"] = .5
    data.loc[data.index[-1], ["Open", "High", "Low", "Close"]] = [price, price + 1, price - 1, price]
    cross_date = data.index[-1-age]
    data["golden_cross"] = False
    data.loc[cross_date, ["golden_cross", "volume_ratio_20"]] = [True, 3.]
    event = dict(STOCK, strong_golden_cross=True, golden_cross_date=cross_date, strong_golden_cross_score=85.)
    return event, data


class EntryTests(unittest.TestCase):
    def analyze(self, price=102., age=2, config=EntryTimingConfig()):
        event, data = fixture(price, age)
        return calculate_entry_analysis(event, data, config)

    def test_distance(self):
        self.assertAlmostEqual(self.analyze()["distance_ma20_pct"], 2.)

    def test_pullback_boundaries(self):
        for price in (100., 102., 103.):
            result = self.analyze(price)
            self.assertEqual(result["entry_status"], "PULLBACK_ZONE")
            self.assertEqual((result["entry_zone_low"], result["entry_zone_high"]), (100., 103.))
            self.assertTrue(result["is_pullback_entry"])

    def test_below_ma20(self):
        self.assertEqual(self.analyze(99.)["entry_status"], "TREND_INVALIDATED")

    def test_watch(self):
        self.assertEqual(self.analyze(105.)["entry_status"], "WATCH")

    def test_extended(self):
        self.assertEqual(self.analyze(112.)["entry_status"], "EXTENDED")

    def test_highly_extended_not_current_entry(self):
        result = self.analyze(118.)
        self.assertEqual(result["entry_status"], "HIGHLY_EXTENDED")
        self.assertEqual(result["entry_reference_price"], 101.5)
        self.assertEqual(result["action"], "WAIT_FOR_PULLBACK")
        self.assertTrue(result["cross_entry_missed"])

    def test_breakout_and_priority(self):
        result = self.analyze(108.5)
        self.assertEqual(result["entry_status"], "BREAKOUT_ZONE")
        self.assertTrue(result["is_cross_entry"])
        self.assertEqual(result["primary_entry_type"], "BREAKOUT")

    def test_resistance_excludes_current(self):
        event, data = fixture(108.5)
        data.loc[data.index[-1], "High"] = 999.
        self.assertEqual(calculate_entry_analysis(event, data)["recent_20d_high"], 108.)

    def test_cross_entry(self):
        event, data = fixture(108.5)
        data.loc[data.index[-1], "volume_ratio_20"] = 1.
        self.assertEqual(calculate_entry_analysis(event, data)["entry_status"], "CROSS_ENTRY")

    def test_old_cross_rejected_trading_sessions(self):
        for age, expected in ((3, True), (4, False)):
            event, data = fixture(108.5, age)
            data.loc[data.index[-1], "volume_ratio_20"] = 1.
            result = calculate_entry_analysis(event, data)
            self.assertEqual(result["cross_age_days"], age)
            self.assertEqual(result["is_cross_entry"], expected)

    def test_histogram_expanding(self):
        self.assertEqual(calculate_histogram_direction(1., .5), "EXPANDING")

    def test_histogram_cooling(self):
        self.assertEqual(calculate_histogram_direction(1., 1.), "COOLING")

    def test_histogram_weak(self):
        self.assertEqual(calculate_histogram_direction(0., 1.), "WEAK")

    def test_atr_matches_existing_and_configurable(self):
        raw = prices(180)
        prev = raw.Close.shift(1)
        tr = pd.concat([raw.High - raw.Low, (raw.High-prev).abs(), (raw.Low-prev).abs()], axis=1).max(axis=1)
        for period in (14, 7):
            np.testing.assert_allclose(calculate_atr(raw, period), tr.rolling(period).mean(), equal_nan=True)

    def test_swing_excludes_current(self):
        event, data = fixture()
        data.loc[data.index[-1], "Low"] = 1.
        self.assertEqual(calculate_entry_analysis(event, data)["recent_swing_low"], 95.)

    def test_stop_and_fallback(self):
        self.assertEqual(self.analyze()["reference_stop"], 95.)
        self.assertEqual(calculate_reference_stop(101.5, 100., 4., 110.)[1:], (98., "MA20_ATR"))
        cfg = EntryTimingConfig(stop_mode="MA20_ATR")
        self.assertEqual(self.analyze(config=cfg)["reference_stop"], 98.)

    def test_risk(self):
        result = self.analyze()
        self.assertEqual(result["risk_per_share"], 6.5)
        self.assertAlmostEqual(result["risk_pct"], 6.5 / 101.5 * 100)

    def test_target_2r(self):
        self.assertEqual(self.analyze()["target_2r"], 114.5)

    def test_target_3r(self):
        self.assertEqual(self.analyze()["target_3r"], 121.)

    def test_invalid_risk_no_targets(self):
        for stop in (101.5, 110., -1., None, float("nan")):
            result = calculate_risk_targets(101.5, stop)
            self.assertEqual(result["risk_status"], "INVALID_RISK_STRUCTURE")
            self.assertIsNone(result["target_2r"])

    def test_missing_unknown(self):
        event, data = fixture()
        for field in ("Close", "MA20", "MA60", "ATR", "Impulse_Histogram"):
            missing = data.copy()
            missing.loc[missing.index[-1], field] = np.nan
            self.assertEqual(calculate_entry_analysis(event, missing)["entry_status"], "UNKNOWN")
        self.assertEqual(calculate_entry_analysis(event, None)["entry_status"], "UNKNOWN")

    def test_no_future_bars_and_cross_date(self):
        event, data = fixture()
        before = calculate_entry_analysis(event, data)
        future = data.iloc[[-1]].copy()
        future.index = pd.DatetimeIndex([data.index[-1] + pd.Timedelta(days=1)])
        future.loc[:, ["High", "Low", "Close"]] = [900., 1., 800.]
        full = pd.concat([data, future])
        self.assertEqual(before, calculate_entry_analysis(event, full, asof=data.index[-1]))
        self.assertEqual(calculate_entry_analysis(event, data, asof=data.index[-4])["entry_status"], "UNKNOWN")

    def test_volume_contraction_optional(self):
        event, data = fixture()
        data.loc[data.index[-1], "volume_ratio_20"] = 4.
        self.assertEqual(calculate_entry_analysis(event, data)["entry_status"], "PULLBACK_ZONE")
        result = calculate_entry_analysis(event, data, EntryTimingConfig(require_volume_contraction=True))
        self.assertFalse(result["volume_contraction"])
        self.assertEqual(result["entry_status"], "WATCH")

    def test_breakout_expansion_config(self):
        event, data = fixture(108.5, 4)
        data.loc[data.index[-1], "Impulse_Histogram"] = .4
        self.assertFalse(calculate_entry_analysis(event, data)["is_breakout_entry"])
        self.assertTrue(calculate_entry_analysis(event, data, EntryTimingConfig(require_expanding_breakout=False))["is_breakout_entry"])

    def test_configuration_validation(self):
        for kwargs in ({"swing_lookback": 0}, {"pullback_high_pct": .2}, {"stop_mode": "BAD"}, {"atr_period": 1.5}):
            with self.assertRaises(ValueError):
                EntryTimingConfig(**kwargs)

    def test_pure_calculation_no_io_or_mutation(self):
        event, data = fixture()
        original, original_event = data.copy(deep=True), copy.deepcopy(event)
        with patch("sqlite3.connect", side_effect=AssertionError("No SQLite IO")), \
             patch("yfinance.download", side_effect=AssertionError("No Yahoo IO")):
            result = analyze_candidates(pd.DataFrame([event]), {event["ticker"]: data})
        self.assertEqual(result.ticker.tolist(), [event["ticker"]])
        self.assertEqual(result.strong_golden_cross_score.tolist(), [85.])
        pd.testing.assert_frame_equal(data, original)
        self.assertEqual(event, original_event)

    def test_real_scanner_results_unchanged(self):
        raw = prices(250)
        close = 100 + np.arange(250) * .3 + 3 * np.sin(np.arange(250) / 6)
        raw.loc[:, ["Open", "Close"]] = np.column_stack([close, close])
        raw["High"], raw["Low"] = close + .5, close - .5
        indicators = calculate_impulse(raw)
        viable = indicators[(indicators.Close > indicators.MA20) & (indicators.MA20 > indicators.MA60)
                            & (indicators.ma20_slope_pct > 0)]
        raw = raw.loc[:viable.index[-1]]
        # Known scanner fixture: supply public revenue without changing selection.
        revenue = pd.DataFrame([dict(stock_code="2330", year_month="2024-11", revenue_yoy=.3, available_at="2024-12-01", revenue=100., updated_at="2024-12-01", revenue_publish_date=None)])
        cfg = ImpulseConfig(cross_lookback_days=250)
        from src.strong_impulse import StrongConfig
        strong = StrongConfig(min_volume_ratio_20=.5, max_revenue_age_months=12)
        snapshot = scan_strong_universe(pd.DataFrame([STOCK]), {STOCK["ticker"]: raw}, revenue, cfg, strong, asof="2024-12-31")
        self.assertFalse(snapshot["candidates"].empty)
        saved = copy.deepcopy(snapshot)
        analyze_candidates(snapshot["candidates"], snapshot["details"], impulse_config=cfg)
        pd.testing.assert_frame_equal(snapshot["candidates"], saved["candidates"])
        pd.testing.assert_frame_equal(snapshot["events"], saved["events"])
        for ticker in saved["details"]:
            pd.testing.assert_frame_equal(snapshot["details"][ticker], saved["details"][ticker])

    def test_panel_existing_snapshot_no_download(self):
        event, data = fixture()
        snapshot = dict(candidates=pd.DataFrame([event]), details={event["ticker"]: data})
        def app():
            import streamlit as st
            from src.entry_timing_panel import render_entry_timing_panel
            from src.impulse_macd import ImpulseConfig
            render_entry_timing_panel(st.session_state.snapshot, ImpulseConfig())
        test = AppTest.from_function(app)
        test.session_state.snapshot = snapshot
        with patch("yfinance.download", side_effect=AssertionError("No download")):
            test.run(timeout=20)
            self.assertFalse(test.exception)
            self.assertEqual(len(test.dataframe), 1)
            self.assertTrue(any("PULLBACK ZONE" in m.value for m in test.markdown))

    def test_unknown_non_candidate_and_missing_cross(self):
        event, data = fixture()
        for change in ({"strong_golden_cross": False}, {"golden_cross_date": "1999-01-01"}):
            result = calculate_entry_analysis(dict(event, **change), data)
            self.assertEqual(result["entry_status"], "UNKNOWN")

    def test_raw_history_prefix_is_causal(self):
        data = calculate_impulse(prices(250))
        cross_date = data.index[data.golden_cross][-1]
        event = dict(STOCK, strong_golden_cross=True, golden_cross_date=cross_date)
        end = data.index.get_loc(cross_date) + 1
        raw = prices(250)
        left = calculate_entry_analysis(event, raw.iloc[:end])
        right = calculate_entry_analysis(event, raw, asof=cross_date)
        self.assertNotEqual(left["entry_status"], "UNKNOWN")
        self.assertEqual(left, right)

    def test_full_page_retains_candidates_and_download_count(self):
        event, data = fixture()
        event.update(current_histogram=1., revenue_status="AVAILABLE", signal_date=event["golden_cross_date"], signal_close=100.)
        snapshot = dict(candidates=pd.DataFrame([event]), events=pd.DataFrame([event]), details={event["ticker"]: data},
                        stats=dict(total=1, candidates=1), market_date=data.index[-1], issues=pd.DataFrame())
        with patch("src.impulse_panel.cached_universe", return_value=(pd.DataFrame([STOCK]), {})), \
             patch("src.impulse_panel.load_incremental_histories", return_value=({STOCK["ticker"]: data}, {})) as history, \
             patch("src.impulse_panel.load_monthly_revenue", return_value=(pd.DataFrame(), {})), \
             patch("src.impulse_panel.scan_strong_universe", return_value=snapshot):
            app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))
            app.switch_page("pages/5_Impulse_MACD.py").run(timeout=20)
            app.selectbox[0].set_value("Strong Golden Cross").run()
            app.button[0].click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertTrue(any("Entry Timing Analysis" in h.value for h in app.subheader))
            self.assertEqual(app.dataframe[0].value.ticker.tolist(), [STOCK["ticker"]])
            next(c for c in app.checkbox if c.label == "Current histogram > 0 (optional confirmation)").check().run()
            self.assertFalse(app.exception)
            history.assert_called_once()


if __name__ == "__main__":
    unittest.main()
