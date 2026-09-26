import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

from backtesting.config import BacktestConfig, TradingCosts
from backtesting.execution import simulate_trade
from tests.test_bull_flag import synthetic, universe
from src.bull_flag_gap import scan_gap_universe, filter_gap_events, to_backtest_signal
from src.bull_flag_gap_config import GapConfig


def gap_history(lows=()):
    data = synthetic(True, 1500)
    data.iloc[-1] = [120, 123, 119, 122, 122, 1500]
    if lows:
        tail = pd.DataFrame([dict(Open=122, High=124, Low=low, Close=123,
                                  **{"Adj Close": 123, "Volume": 1000}) for low in lows],
                            index=pd.bdate_range(data.index[-1] + pd.Timedelta(days=1), periods=len(lows)))
        data = pd.concat([data, tail])
    return data


class GapTests(unittest.TestCase):
    def scan(self, data, config=GapConfig(), sessions=None):
        return scan_gap_universe(universe(), {"2330.TW": data}, config, market_sessions=sessions)

    def event(self, data, config=GapConfig()):
        result = self.scan(data, config)
        self.assertFalse(result["events"].empty, result["issues"])
        return result["events"].iloc[0]

    def test_full_gap_and_reused_bull_flag(self):
        data = gap_history([120, 121])
        result = self.scan(data)
        event = result["events"].iloc[0]
        self.assertEqual(len(result["candidates"]), 1)
        self.assertGreater(event.breakout_close, event.upper_flag_trendline)
        self.assertGreater(event.breakout_MA20, event.breakout_MA60)
        self.assertGreater(event.breakout_MA20_slope, 0)
        self.assertEqual(event.gap_status, "UNTOUCHED")
        self.assertAlmostEqual(event.gap_bottom, 117.2)
        self.assertEqual(event.gap_top, 119)
        self.assertEqual(event.trading_days_since_gap, 2)
        self.assertEqual(event.remaining_gap_pct, 1)
        self.assertGreaterEqual(event.gap_breakout_score, 0)
        self.assertLessEqual(event.gap_breakout_score, 100)

    def test_breakout_without_gap_and_gap_without_flag(self):
        self.assertTrue(self.scan(synthetic(True, 1500))["events"].empty)
        data = gap_history()
        close = np.linspace(75, 120, len(data) - 1)
        for column in ("Open", "High", "Low", "Close", "Adj Close"):
            data.iloc[:-1, data.columns.get_loc(column)] = close + (1 if column == "High" else -1 if column == "Low" else 0)
        data.iloc[-1] = [125, 129, 124, 128, 128, 1500]
        self.assertTrue(self.scan(data)["events"].empty)

    def test_lookback_counts_market_sessions_including_latest(self):
        data = gap_history([120] * 20)
        self.assertTrue(self.scan(data)["events"].empty)
        row = self.event(data, replace(GapConfig(), gap_lookback_days=30))
        self.assertEqual(row.trading_days_since_gap, 20)
        self.assertEqual(len(self.scan(gap_history([120] * 19))["candidates"]), 1)

    def test_partial_fill_remaining_gap_and_boundary_touch(self):
        partial = self.event(gap_history([120, 118.1, 121]))
        self.assertEqual(partial.gap_status, "PARTIALLY_FILLED")
        self.assertAlmostEqual(partial.gap_fill_pct, .5)
        self.assertAlmostEqual(partial.remaining_gap_size, .9)
        self.assertAlmostEqual(partial.lowest_price_after_gap, 118.1)
        touched = self.event(gap_history([119]))
        self.assertEqual(touched.gap_status, "PARTIALLY_FILLED")
        self.assertEqual(touched.gap_fill_pct, 0)
        result = self.scan(gap_history([119]), replace(GapConfig(), only_untouched_gaps=True))
        self.assertTrue(result["candidates"].empty)

    def test_fully_filled_and_first_fill_date(self):
        data = gap_history([118, 117.2, 116, 121])
        result = self.scan(data)
        event = result["events"].iloc[0]
        self.assertEqual(event.gap_status, "FILLED")
        self.assertEqual(event.gap_fill_pct, 1)
        self.assertEqual(event.remaining_gap_size, 0)
        self.assertEqual(event.days_until_gap_fill, 2)
        self.assertEqual(event.gap_fill_date, data.index[-3])
        self.assertTrue(result["candidates"].empty)
        self.assertEqual(len(filter_gap_events(result["events"], statuses=["FILLED"])), 1)

    def test_latest_event_has_no_subsequent_low(self):
        event = self.event(gap_history())
        self.assertEqual(event.gap_status, "UNTOUCHED")
        self.assertTrue(pd.isna(event.lowest_price_after_gap))
        self.assertTrue(event.fill_data_complete)

    def test_open_gap_own_day_can_fill(self):
        data = gap_history()
        data.iloc[-1, data.columns.get_loc("Low")] = 116
        self.assertTrue(self.scan(data)["events"].empty)
        event = self.event(data, replace(GapConfig(), gap_definition="OPEN_GAP"))
        self.assertEqual(event.gap_top, 120)
        self.assertEqual(event.gap_status, "FILLED")
        self.assertEqual(event.gap_fill_date, event.gap_date)
        self.assertEqual(event.days_until_gap_fill, 0)
        self.assertIsNone(to_backtest_signal(event))

    def test_open_gap_partial_on_gap_day(self):
        data = gap_history()
        data.iloc[-1, data.columns.get_loc("Low")] = 118.5
        event = self.event(data, replace(GapConfig(), gap_definition="OPEN_GAP"))
        self.assertEqual(event.gap_status, "PARTIALLY_FILLED")
        self.assertAlmostEqual(event.gap_fill_pct, 1.5 / 2.8)

    def test_minimum_gap_and_volume_confirmation(self):
        data = gap_history()
        self.assertTrue(self.scan(data, replace(GapConfig(), min_gap_pct=.02))["events"].empty)
        data.iloc[-1, data.columns.get_loc("Volume")] = 500
        self.assertTrue(self.scan(data)["events"].empty)
        self.assertEqual(len(self.scan(data, replace(GapConfig(), require_gap_volume_confirmation=False))["events"]), 1)

    def test_future_data_does_not_change_historical_event_or_signal_score(self):
        first = self.event(gap_history())
        second = self.event(gap_history([120, 116, 121]))
        for key in ("bull_flag_score", "gap_score_at_signal", "high_slope", "low_slope", "breakout_date",
                    "gap_top", "gap_bottom", "upper_flag_trendline", "signal_date", "gap_status_at_signal"):
            self.assertEqual(first[key], second[key], key)
        self.assertEqual(second.gap_status, "FILLED")
        self.assertIsNotNone(to_backtest_signal(second))

    def test_missing_future_bar_never_certifies_unfilled(self):
        data = gap_history([120, 120, 120])
        data.iloc[-2, data.columns.get_loc("Low")] = np.nan
        result = self.scan(data)
        self.assertEqual(len(result["events"]), 1)
        self.assertFalse(result["events"].iloc[0].fill_data_complete)
        self.assertTrue(result["candidates"].empty)
        missing_date = gap_history([120, 120, 120])
        result = self.scan(missing_date.drop(missing_date.index[-2]), sessions=missing_date.index)
        self.assertTrue(result["candidates"].empty)

    def test_stale_suspended_and_bad_history(self):
        data = gap_history([120, 120])
        result = self.scan(data.iloc[:-1], sessions=data.index)
        self.assertEqual(result["stats"]["skipped"], 1)
        data.iloc[-2, data.columns.get_loc("Volume")] = 0
        self.assertTrue(self.scan(data, sessions=data.index)["candidates"].empty)
        self.assertEqual(self.scan(data.drop(columns="High"))["stats"]["skipped"], 1)

    def test_corporate_actions_and_adjustment_artifacts(self):
        data = gap_history()
        data["Dividends"] = 0.0
        data.iloc[-1, data.columns.get_loc("Dividends")] = 1
        self.assertTrue(self.scan(data)["events"].empty)
        data = gap_history()
        data.iloc[-1, data.columns.get_loc("Adj Close")] *= .5
        self.assertTrue(self.scan(data)["events"].empty)
        data = gap_history([120])
        data["Stock Splits"] = 0.0
        data.iloc[-1, data.columns.get_loc("Stock Splits")] = 2
        result = self.scan(data)
        self.assertEqual(len(result["events"]), 1)
        self.assertTrue(result["candidates"].empty)

    def test_multiple_real_flags_newest_qualifying_gap_selected(self):
        data = gap_history()
        prices = np.concatenate([np.linspace(125, 160, 20), 159 - np.arange(8) * .4, [162]])
        tail = pd.DataFrame(dict(Open=prices - .2, High=prices + 1, Low=prices - 1,
                                 Close=prices, Volume=1000.0),
                            index=pd.bdate_range(data.index[-1] + pd.Timedelta(days=1), periods=len(prices)))
        tail["Adj Close"] = tail.Close
        tail.iloc[-9:-1, tail.columns.get_loc("Volume")] = 400
        tail.iloc[-1, tail.columns.get_loc("Volume")] = 1500
        result = self.scan(pd.concat([data, tail]), replace(GapConfig(), gap_lookback_days=60))
        self.assertGreaterEqual(len(result["events"]), 2)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"].iloc[0].gap_date, tail.index[-1])
        events = result["events"].copy()
        events.loc[events.gap_date == tail.index[-1], "gap_status"] = "FILLED"
        self.assertEqual(filter_gap_events(events).iloc[0].gap_date, data.index[-1])

    def test_backtest_adapter_uses_existing_execution(self):
        result = self.scan(gap_history([120, 121]))
        event = result["events"].iloc[0]
        adapted = to_backtest_signal(event)
        self.assertNotIn("gap_fill_pct", adapted)
        self.assertNotIn("gap_breakout_score", adapted)
        trade, error = simulate_trade(result["details"]["2330.TW"], adapted, 2, 2,
                                      BacktestConfig(costs=TradingCosts(enabled=False)))
        self.assertIsNone(error)
        self.assertGreater(trade["entry_date"], event.signal_date)

    def test_adjacent_day_window_recognizes_only_when_both_known(self):
        data = synthetic(True, 1500)
        tail = pd.DataFrame([dict(Open=122, High=124, Low=121, Close=123,
                                 Volume=1000, **{"Adj Close": 123})], index=[data.index[-1] + pd.offsets.BDay()])
        data = pd.concat([data, tail])
        self.assertTrue(self.scan(data)["events"].empty)
        event = self.event(data, replace(GapConfig(), gap_breakout_window=1))
        self.assertEqual(event.gap_breakout_offset, 1)
        self.assertEqual(event.signal_date, tail.index[0])
        self.assertLess(event.breakout_date, event.signal_date)


if __name__ == "__main__":
    unittest.main()
