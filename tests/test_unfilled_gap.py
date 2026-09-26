import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

from backtesting.config import BacktestConfig, TradingCosts
from src.unfilled_gap import (prepare_trend_history, scan_unfilled_universe, filter_unfilled_events,
                              trend_passes, trend_mode_passes, to_unfilled_backtest_signal, compare_trend_variants)
from src.unfilled_gap_config import UnfilledGapConfig, TrendConfig
from tests.test_bull_flag import universe


def unfilled_history(tail=3):
    prices = np.concatenate([np.linspace(70, 100, 140), [110], 112 + np.arange(tail) * .5])
    data = pd.DataFrame(dict(Open=prices, High=prices + 1, Low=prices - 1, Close=prices,
                            Volume=1000.0), index=pd.bdate_range("2025-01-01", periods=len(prices)))
    data["Adj Close"] = data.Close
    data.iloc[140, data.columns.get_loc("Low")] = 108
    data.iloc[140, data.columns.get_loc("Volume")] = 2000
    return data


def relaxed_trend(**kwargs):
    return TrendConfig(require_close_above_ma20=False, require_ma20_above_ma60=False,
                       require_ma20_rising=False, **kwargs)


class UnfilledTrendTests(unittest.TestCase):
    def scan(self, data, config=UnfilledGapConfig()):
        return scan_unfilled_universe(universe(), {"2330.TW": data}, config)

    def test_default_strategy_and_component_totals(self):
        result = self.scan(unfilled_history())
        self.assertEqual(len(result["candidates"]), 1)
        row = result["candidates"].iloc[0]
        self.assertGreater(row.recent_return_pct, .1)
        self.assertGreater(row.current_close, row.current_ma20)
        self.assertGreater(row.current_ma20, row.current_ma60)
        self.assertGreater(row.gap_day_ma20, row.gap_day_ma60)
        self.assertGreater(row.current_ma20_slope_pct, 0)
        components = [v for k, v in row.items() if k.startswith("score_") and k != "score_at_signal"]
        self.assertAlmostEqual(sum(components), row.unfilled_gap_score, delta=.03)
        self.assertLessEqual(row.unfilled_gap_score, 100)

    def test_normalized_multiday_slope_exact(self):
        data = unfilled_history()
        for lookback in (5, 10):
            prepared = prepare_trend_history(data, UnfilledGapConfig(trend=TrendConfig(ma_slope_lookback=lookback)))
            for period in (20, 60):
                expected = prepared[f"MA{period}"].iloc[-1] / prepared[f"MA{period}"].iloc[-1 - lookback] - 1
                self.assertAlmostEqual(prepared[f"ma{period}_slope_pct"].iloc[-1], expected)

    def test_each_ma_gate_can_be_disabled_independently(self):
        event = self.scan(unfilled_history())["events"].iloc[0].to_dict()
        mapping = {"require_close_above_ma20": "close_above_ma20", "require_ma20_above_ma60": "ma20_above_ma60",
                   "require_ma20_rising": "ma20_rising", "require_ma60_rising": "ma60_rising",
                   "require_full_ma_alignment": "full_ma_alignment"}
        for flag, field in mapping.items():
            with self.subTest(flag=flag):
                cfg = replace(relaxed_trend(), **{flag: True})
                changed = dict(event, **{f"gap_day_{field}": False})
                self.assertFalse(trend_passes(changed, "gap_day", cfg))
                changed[f"gap_day_{field}"] = True
                self.assertTrue(trend_passes(changed, "gap_day", cfg))
                changed[f"gap_day_{field}"] = False
                self.assertTrue(trend_passes(changed, "gap_day", relaxed_trend()))

    def test_gap_day_current_and_both_modes(self):
        event = self.scan(unfilled_history())["events"].iloc[0].to_dict()
        for gap_ok, current_ok in ((True, False), (False, True), (True, True), (False, False)):
            event["gap_day_ma20_above_ma60"] = gap_ok
            event["current_ma20_above_ma60"] = current_ok
            for mode, expected in (("GAP_DAY", gap_ok), ("CURRENT", current_ok), ("GAP_DAY_AND_CURRENT", gap_ok and current_ok)):
                self.assertEqual(trend_mode_passes(event, replace(TrendConfig(), trend_evaluation=mode)), expected)

    def test_real_falling_ma_and_downtrend(self):
        data = unfilled_history()
        descending = np.linspace(140, 70, len(data))
        for name in ("Open", "High", "Low", "Close", "Adj Close"):
            data[name] = descending + (1 if name == "High" else -1 if name == "Low" else 0)
        prepared = prepare_trend_history(data)
        self.assertLess(prepared.MA20.iloc[-1], prepared.MA60.iloc[-1])
        self.assertLess(prepared.Close.iloc[-1], prepared.MA20.iloc[-1])
        self.assertLess(prepared.ma20_slope_pct.iloc[-1], 0)
        self.assertLess(prepared.ma60_slope_pct.iloc[-1], 0)
        self.assertTrue(self.scan(data)["candidates"].empty)

    def test_current_close_fails_while_gap_day_passes(self):
        data = unfilled_history(12)
        data.iloc[-1, data.columns.get_loc("Open")] = 104
        data.iloc[-1, data.columns.get_loc("High")] = 105
        data.iloc[-1, data.columns.get_loc("Low")] = 103
        data.iloc[-1, data.columns.get_loc("Close")] = 104
        data.iloc[-1, data.columns.get_loc("Adj Close")] = 104
        cfg = UnfilledGapConfig(min_return_pct=0)
        result = self.scan(data, cfg)
        original = result["events"][result["events"].gap_date == data.index[140]].iloc[0]
        self.assertTrue(original.gap_day_trend_pass)
        self.assertFalse(original.current_trend_pass)
        self.assertFalse(trend_mode_passes(original, cfg.trend))
        self.assertTrue(trend_mode_passes(original, replace(cfg.trend, trend_evaluation="GAP_DAY")))

    def test_full_alignment_and_ma60_rising(self):
        result = self.scan(unfilled_history(), UnfilledGapConfig(trend=TrendConfig(require_full_ma_alignment=True, require_ma60_rising=True)))
        self.assertEqual(len(result["candidates"]), 1)

    def test_distance_bounds_and_recent_return_threshold(self):
        result = self.scan(unfilled_history())
        events = result["events"]
        cfg = UnfilledGapConfig(trend=TrendConfig(enable_distance_filter=True, min_ma20_ma60_distance_pct=.5))
        self.assertTrue(filter_unfilled_events(events, cfg).empty)
        self.assertTrue(filter_unfilled_events(events, UnfilledGapConfig(min_return_pct=.8)).empty)

    def test_golden_cross_detected_and_initial_bullish_unknown(self):
        data = unfilled_history(60)
        prices = np.concatenate([np.linspace(130, 80, 90), np.linspace(80, 150, len(data) - 90)])
        for name in ("Open", "High", "Low", "Close", "Adj Close"):
            data[name] = prices + (1 if name == "High" else -1 if name == "Low" else 0)
        prepared = prepare_trend_history(data)
        crossed = prepared.index[(prepared.MA20 > prepared.MA60) & (prepared.MA20.shift(1) <= prepared.MA60.shift(1))][-1]
        self.assertEqual(prepared.ma20_ma60_cross_date.iloc[-1], crossed)
        self.assertEqual(prepared.trading_days_since_golden_cross.iloc[-1], len(data) - 1 - data.index.get_loc(crossed))
        self.assertTrue(pd.isna(prepare_trend_history(unfilled_history()).ma20_ma60_cross_date.iloc[-1]))

    def test_future_prices_cannot_change_gap_day_or_signal_fields(self):
        first = self.scan(unfilled_history(0))["events"].iloc[0]
        later = self.scan(unfilled_history(10))["events"].iloc[0]
        for key in first.index:
            if key.startswith("gap_day_") or key in ("signal_atr", "score_at_signal", "signal_close"):
                if pd.isna(first[key]):
                    self.assertTrue(pd.isna(later[key]))
                else:
                    self.assertEqual(first[key], later[key], key)

    def test_missing_history_blocks_current_certification(self):
        data = unfilled_history(3)
        data.iloc[-2, data.columns.get_loc("Low")] = np.nan
        self.assertTrue(self.scan(data)["candidates"].empty)

    def test_backtest_adapter_ignores_future_status_and_current_ma(self):
        event = self.scan(unfilled_history())["events"].iloc[0].to_dict()
        original = to_unfilled_backtest_signal(event)
        changed = dict(event, current_ma20=999, current_ma60=9999, gap_status="FILLED",
                       current_recent_return_pct=-.8, recent_return_pct=-.8)
        self.assertEqual(original, to_unfilled_backtest_signal(changed))
        self.assertNotIn("current_ma20", original)

    def test_five_backtest_variants_reuse_execution_and_forward_returns(self):
        cfg = UnfilledGapConfig(gap_lookback_days=60)
        result = self.scan(unfilled_history(35), cfg)
        variants = compare_trend_variants(result["events"], result["details"], cfg,
                                          BacktestConfig(costs=TradingCosts(enabled=False)))
        self.assertEqual(len(variants), 5)
        for report in variants.values():
            self.assertFalse(report["trades"].empty)
            self.assertIn("return_30d", report["forward_returns"])
            self.assertEqual(len(report["comparison"]), 20)


if __name__ == "__main__":
    unittest.main()
