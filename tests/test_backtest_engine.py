import unittest
from dataclasses import replace

import pandas as pd

from tests.test_bull_flag import synthetic, universe
from tests.test_backtest_execution import bars
from backtesting.config import BacktestConfig, TradingCosts
from backtesting.signals import prepare_history, generate_signals
from backtesting.engine import build_signal_set, execute_backtest, run_backtest
from src.bull_flag_config import BullFlagConfig


def historical_sample():
    history = synthetic(True, 1500)
    future = bars([(119, 122, 118, 121), (122, 127, 121, 126), (126, 131, 125, 130)] * 11)
    future.index = pd.bdate_range(history.index[-1] + pd.Timedelta(days=1), periods=len(future))
    return pd.concat([history, future])


class EngineTests(unittest.TestCase):
    config = BacktestConfig(detector=BullFlagConfig(min_flag_days=8, max_flag_days=8),
                            costs=TradingCosts(enabled=False))

    def test_real_detector_historical_signal_and_next_open(self):
        result = run_backtest(universe(), {"2330.TW": historical_sample()}, self.config)
        self.assertGreater(len(result["signals"]), 0)
        signal = result["signals"].iloc[0]
        self.assertEqual(signal.signal_date, synthetic().index[-1])
        trade = result["trades"].iloc[0]
        self.assertGreater(trade.entry_date, trade.signal_date)
        self.assertEqual(trade.entry_price, 119)
        self.assertEqual(len(result["comparison"]), 20)

    def test_future_candles_and_adjusted_prices_cannot_change_past_signals(self):
        data = historical_sample()
        cutoff = synthetic().index[-1]
        first = build_signal_set(universe(), {"2330.TW": data.loc[:cutoff]}, self.config)["signals"]
        changed = data.copy()
        changed.loc[changed.index > cutoff, ["Open", "High", "Low", "Close"]] *= 4
        changed["Adj Close"] *= .2
        after = build_signal_set(universe(), {"2330.TW": changed}, self.config, signal_end=cutoff)["signals"]
        pd.testing.assert_frame_equal(first, after)
        changed.loc[changed.index[-1], "High"] = float("nan")
        after_missing = build_signal_set(universe(), {"2330.TW": changed}, self.config, signal_end=cutoff)["signals"]
        pd.testing.assert_frame_equal(first, after_missing)

    def test_positive_ma20_slope_required_and_volume_optional(self):
        cfg = replace(self.config, require_breakout_volume=False)
        low_volume = synthetic(True, 500)
        prepared = prepare_history(low_volume, cfg)
        signals = generate_signals(prepared, universe().iloc[0].to_dict(), cfg)
        self.assertEqual(len(signals), 1)
        self.assertEqual(generate_signals(prepared, universe().iloc[0].to_dict(), self.config), [])
        prepared.loc[prepared.index[-1], "MA20_slope"] = -1
        self.assertEqual(generate_signals(prepared, universe().iloc[0].to_dict(), cfg), [])

    def test_missing_short_and_duplicate_history_isolated(self):
        for data in (synthetic().iloc[:20], synthetic().drop(columns="High"),
                     pd.concat([synthetic(), synthetic().tail(1)])):
            with self.subTest(rows=len(data)):
                result = run_backtest(universe(), {"2330.TW": data}, self.config)
                self.assertTrue(result["trades"].empty)
                self.assertTrue(result["issues"])

    def test_overlap_blocking_and_opt_in(self):
        data = prepare_history(historical_sample(), self.config)
        signals = generate_signals(data, universe().iloc[0].to_dict(), self.config)
        original = signals[0]
        second = dict(original, signal_index=original["signal_index"] + 1,
                      signal_date=data.index[original["signal_index"] + 1], signal_id="second")
        bundle = dict(signals=pd.DataFrame([original, second]), histories={"2330.TW": data}, issues=[], stats={})
        cfg = replace(self.config, rr_targets=(3.0,), holding_periods=(20,))
        result = execute_backtest(bundle, cfg)
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["skipped"].reason.tolist(), ["Overlapping position"])
        self.assertEqual(len(execute_backtest(bundle, replace(cfg, allow_overlap=True))["trades"]), 2)

    def test_training_does_not_use_test_bars(self):
        data = historical_sample()
        split = data.index[len(synthetic()) + 1]
        result = run_backtest(universe(), {"2330.TW": data}, self.config, split_date=split)
        train = result["trades"][result["trades"]["sample"] == "TRAIN"]
        self.assertTrue((train.exit_date < split).all())
        self.assertTrue((train.outcome == "CENSORED").any())


if __name__ == "__main__":
    unittest.main()
