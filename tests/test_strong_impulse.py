from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from services.monthly_revenue import parse_revenue, load_monthly_revenue, revenue_asof
from src.impulse_macd import calculate_impulse, historical_cross_events, ImpulseConfig
from src.strong_impulse import StrongConfig, describe_event, scan_strong_universe
from backtesting.impulse import compare_impulse_variants
from backtesting.config import BacktestConfig
from tests.test_impulse_macd import prices, STOCK


def fixture():
    data = calculate_impulse(prices())
    pos = len(data) - 3
    data.loc[data.index[pos], ["Impulse_MACD", "Impulse_Signal", "Impulse_Histogram", "golden_cross", "volume_ratio_20", "daily_return"]] = [2., 1., 1., True, 1.5, .02]
    data.loc[data.index[pos - 1], ["Impulse_MACD", "Impulse_Signal"]] = [0., 1.]
    data.loc[data.index[-1], ["Close", "MA20", "MA60", "ma20_slope_pct", "volume_ratio_20"]] = [120., 110., 100., .02, 1.]
    event = dict(STOCK, signal_id="test", signal_index=pos, signal_date=data.index[pos], golden_cross_date=data.index[pos], signal_close=110.)
    now = data.index[-1] + pd.Timedelta(hours=14)
    revenue = pd.DataFrame([dict(stock_code="2330", year_month=str(now.to_period("M") - 1), revenue=130., revenue_yoy=.3,
                                available_at=str(data.index[pos] - pd.Timedelta(days=1)), updated_at=str(now), revenue_publish_date=None)])
    return data, event, revenue, now


class StrongTests(unittest.TestCase):
    def test_all_conditions_true(self):
        data, event, rev, now = fixture()
        result = describe_event(event, data, rev, asof=now)
        self.assertTrue(result["strong_golden_cross"])
        self.assertEqual(result["failed_conditions"], [])
        self.assertLessEqual(result["strong_golden_cross_score"], 100)

    def test_each_mandatory_condition_fails_independently(self):
        for column, value, target in [("golden_cross", False, "impulse_golden_cross"), ("Impulse_MACD", -1., "above_zero"),
                                       ("volume_ratio_20", 1.49, "volume_expansion")]:
            data, event, rev, now = fixture()
            data.loc[data.index[event["signal_index"]], column] = value
            result = describe_event(event, data, rev, asof=now)
            self.assertFalse(result["strong_golden_cross"])
            self.assertIn(target, result["failed_conditions"])
        for col, value, target in [("Close", 90., "close_above_ma20"), ("MA60", 115., "ma20_above_ma60"), ("ma20_slope_pct", 0., "ma20_rising")]:
            data, event, rev, now = fixture()
            data.loc[data.index[-1], col] = value
            result = describe_event(event, data, rev, asof=now)
            self.assertIn(target, result["failed_conditions"])

    def test_volume_threshold_and_all_timing_modes(self):
        data, event, rev, now = fixture()
        for value, expected in [(1.49, False), (1.5, True), (1.51, True), (np.nan, False)]:
            data.loc[data.index[event["signal_index"]], "volume_ratio_20"] = value
            self.assertEqual(describe_event(event, data, rev, asof=now)["condition_volume_expansion"], expected)
        data.loc[data.index[event["signal_index"]], "volume_ratio_20"] = 1.5
        for mode, expected in [("CROSS_DAY", True), ("CURRENT", False), ("CROSS_DAY_OR_CURRENT", True), ("CROSS_DAY_AND_CURRENT", False)]:
            result = describe_event(event, data, rev, StrongConfig(volume_evaluation_mode=mode), now)
            self.assertEqual(result["condition_volume_expansion"], expected)
        data.loc[data.index[event["signal_index"]], "volume_ratio_20"] = 4.
        self.assertEqual(describe_event(event, data, rev, asof=now)["volume_flag"], "EXTREME_VOLUME")

    def test_revenue_strict_boundary_and_unknown(self):
        data, event, rev, now = fixture()
        for value, expected in [(.099, False), (.10, False), (.10001, True), (np.nan, False)]:
            rev["revenue_yoy"] = value
            result = describe_event(event, data, rev, asof=now)
            self.assertEqual(result["strong_golden_cross"], expected)
        result = describe_event(event, data, pd.DataFrame(), asof=now)
        self.assertEqual(result["revenue_status"], "UNKNOWN")
        self.assertTrue(np.isnan(result["revenue_yoy"]))
        rev["year_month"] = str(now.to_period("M") - 4)
        self.assertEqual(describe_event(event, data, rev, asof=now)["revenue_status"], "STALE")

    def test_signal_date_and_current_values_separate(self):
        data, event, rev, now = fixture()
        data.loc[data.index[-1], "Impulse_MACD"] = -100.
        result = describe_event(event, data, rev, asof=now)
        self.assertEqual(result["cross_zone"], "ABOVE_ZERO")
        self.assertEqual(result["cross_date_impulse_macd"], 2.)
        self.assertEqual(result["cross_day_volume_ratio_20"], 1.5)
        self.assertEqual(result["current_volume_ratio_20"], 1.)
        self.assertEqual(result["MA20"], 110.)

    def test_future_revenue_unavailable_and_revision_asof(self):
        data, event, rev, now = fixture()
        later = rev.copy()
        later["available_at"] = str(now + pd.Timedelta(days=1))
        later["revenue_yoy"] = 5.
        both = pd.concat([rev, later])
        self.assertEqual(revenue_asof(both, "2330", now)["revenue_yoy"], .3)
        self.assertEqual(revenue_asof(later, "2330", now)["revenue_status"], "UNKNOWN")
        self.assertEqual(revenue_asof(both, "2330", now + pd.Timedelta(days=2))["revenue_yoy"], 5.)

    def test_score_cannot_override_failure_and_optional_price(self):
        data, event, rev, now = fixture()
        rev["revenue_yoy"] = .1
        result = describe_event(event, data, rev, asof=now)
        self.assertFalse(result["strong_golden_cross"])
        self.assertGreater(result["strong_golden_cross_score"], 0)
        data.loc[data.index[event["signal_index"]], "daily_return"] = -.01
        result = describe_event(event, data, rev, StrongConfig(require_positive_cross_day_return=True), now)
        self.assertIn("positive_cross_day_return", result["failed_conditions"])
        self.assertIn("revenue_growth", result["failed_conditions"])

    def test_inclusive_five_day_age(self):
        raw = prices()
        pos = historical_cross_events(calculate_impulse(raw), STOCK)[-1]["signal_index"]
        run = scan_strong_universe(pd.DataFrame([STOCK]), {"2330.TW": raw.iloc[:pos + 6]}, pd.DataFrame())
        self.assertIn(5, run["events"].trading_days_since_cross.tolist())

    def test_official_parser_ratio_units_and_zero_base(self):
        row = {"公司代號": "2330", "資料年月": "11508", "營業收入-當月營收": "1,100", "營業收入-去年當月營收": "1000", "出表日期": "1150917"}
        parsed = parse_revenue([row], "official")[0]
        self.assertEqual(parsed["year_month"], "2026-08")
        self.assertEqual(parsed["revenue_yoy"], .10)
        self.assertIsNone(parsed["revenue_publish_date"])
        row["營業收入-去年當月營收"] = "0"
        self.assertIsNone(parse_revenue([row], "official")[0]["revenue_yoy"])

    def test_cache_ttl_revisions_and_first_observed(self):
        response = Mock()
        row = {"公司代號": "2330", "資料年月": "11508", "營業收入-當月營收": "1100", "營業收入-去年當月營收": "1000"}
        response.json.return_value = [row]
        session = Mock()
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as temp, patch("services.monthly_revenue.SOURCES", {"TWSE": "official"}):
            path = Path(temp) / "prices.db"
            first, _ = load_monthly_revenue(path, now="2026-09-20 15:00", session=session)
            load_monthly_revenue(path, now="2026-09-20 16:00", session=session)
            session.get.assert_called_once()
            row["營業收入-當月營收"] = "1400"
            revised, _ = load_monthly_revenue(path, refresh=True, now="2026-09-21 15:00", session=session)
            self.assertEqual(len(revised), 2)
            self.assertEqual(revenue_asof(revised, "2330", "2026-09-20 16:00")["revenue_yoy"], .1)
            self.assertEqual(revenue_asof(revised, "2330", "2026-09-19")["revenue_status"], "UNKNOWN")
            row["營業收入-當月營收"] = "1100"
            reverted, _ = load_monthly_revenue(path, refresh=True, now="2026-09-22 15:00", session=session)
            self.assertEqual(len(reverted), 3)
            self.assertEqual(revenue_asof(reverted, "2330", "2026-09-22 16:00")["revenue_yoy"], .1)

    def test_backtest_uses_existing_engine_and_no_future_revenue(self):
        raw = prices()
        _, _, revenue, now = fixture()
        revenue["available_at"] = "2030-01-01"
        run = compare_impulse_variants(pd.DataFrame([STOCK]), {"2330.TW": raw}, revenue,
                                       execution=BacktestConfig(stop_method="ATR", holding_periods=(5,), rr_targets=(2.,)))
        self.assertEqual(len(run["comparison"]), 6)
        self.assertGreater(len(run["trades"]), 0)
        self.assertTrue((run["trades"].entry_date > run["trades"].signal_date).all())
        self.assertEqual(run["comparison"].set_index("variant").loc["F_REVENUE", "total_signals"], 0)
        self.assertTrue((run["all_signals"].revenue_status == "UNKNOWN").all())
        prefix = compare_impulse_variants(pd.DataFrame([STOCK]), {"2330.TW": raw.iloc[:180]}, revenue,
                                          execution=BacktestConfig(stop_method="ATR", holding_periods=(5,), rr_targets=(2.,)))
        before = run["all_signals"][run["all_signals"].signal_index < 180].reset_index(drop=True)
        pd.testing.assert_frame_equal(before, prefix["all_signals"].reset_index(drop=True))

    def test_strong_preset_and_explainability_toggle_no_download(self):
        raw = prices()
        with patch("src.impulse_panel.cached_universe", return_value=(pd.DataFrame([STOCK]), {})), \
             patch("src.impulse_panel.load_incremental_histories", return_value=({"2330.TW": raw}, {})) as history, \
             patch("src.impulse_panel.load_monthly_revenue", return_value=(pd.DataFrame(), {})) as revenue:
            app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))
            app.switch_page("pages/5_Impulse_MACD.py").run(timeout=20)
            app.selectbox[0].set_value("Strong Golden Cross").run()
            self.assertTrue(next(c for c in app.checkbox if c.label == "Current MA20 Rising").value)
            app.button[0].click().run(timeout=20)
            self.assertFalse(app.exception)
            toggle = next(c for c in app.checkbox if c.label == "Show Strong Candidates Only")
            self.assertTrue(toggle.value)
            toggle.uncheck().run()
            self.assertFalse(app.exception)
            history.assert_called_once()
            revenue.assert_called_once()


if __name__ == "__main__":
    unittest.main()
