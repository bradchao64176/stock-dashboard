import unittest
from dataclasses import replace

import pandas as pd

from backtesting.config import BacktestConfig, TradingCosts
from backtesting.execution import simulate_trade, stop_price


def bars(rows):
    frame = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"],
                         index=pd.bdate_range("2025-01-01", periods=len(rows)))
    frame["Volume"] = 10000
    frame["Adj Close"] = frame.Close
    return frame


def signal():
    return dict(signal_index=0, signal_date=pd.Timestamp("2025-01-01"), ticker="2330.TW",
                flag_swing_low=95.0, signal_atr=2.0)


class ExecutionTests(unittest.TestCase):
    config = BacktestConfig(costs=TradingCosts(enabled=False), sizing_mode="FIXED_SHARES", position_shares=1000)

    def trade(self, rows, rr=2, horizon=2, config=None):
        result, error = simulate_trade(bars([(98, 100, 97, 99)] + rows), signal(), rr, horizon, config or self.config)
        self.assertIsNone(error)
        return result

    def test_target_before_stop_and_entry_next_open(self):
        trade = self.trade([(100, 111, 99, 110), (90, 92, 88, 89)])
        self.assertEqual(trade["outcome"], "WIN")
        self.assertEqual(trade["entry_date"], pd.Timestamp("2025-01-02"))
        self.assertEqual(trade["entry_price"], 100)
        self.assertEqual(trade["result_R"], 2)
        self.assertEqual(trade["holding_days"], 1)

    def test_stop_before_target(self):
        trade = self.trade([(100, 101, 94, 96), (110, 112, 109, 111)])
        self.assertEqual(trade["outcome"], "LOSS")
        self.assertEqual(trade["result_R"], -1)

    def test_timeout_and_partial_history_censored(self):
        trade = self.trade([(100, 104, 98, 102), (102, 106, 99, 103)])
        self.assertEqual(trade["outcome"], "TIMEOUT")
        self.assertAlmostEqual(trade["result_R"], .6)
        short = self.trade([(100, 104, 98, 102)])
        self.assertEqual(short["outcome"], "CENSORED")
        self.assertTrue(pd.isna(short["result_R"]))

    def test_same_bar_policies(self):
        for policy, outcome, r in (("CONSERVATIVE", "LOSS", -1), ("OPTIMISTIC", "WIN", 2), ("EXCLUDE", "AMBIGUOUS", None)):
            with self.subTest(policy=policy):
                trade = self.trade([(100, 112, 94, 105)], config=replace(self.config, same_bar_policy=policy))
                self.assertEqual(trade["outcome"], outcome)
                self.assertTrue(trade["same_bar_ambiguous"])
                if r is not None:
                    self.assertEqual(trade["result_R"], r)

    def test_gap_below_stop_and_above_target(self):
        for opening, high, low, outcome, r in ((90, 112, 88, "LOSS", -2), (115, 116, 90, "WIN", 3)):
            trade = self.trade([(100, 104, 97, 101), (opening, high, low, opening)])
            self.assertEqual(trade["outcome"], outcome)
            self.assertEqual(trade["exit_price"], opening)
            self.assertEqual(trade["result_R"], r)
            self.assertFalse(trade["same_bar_ambiguous"])

    def test_stop_models(self):
        self.assertEqual(stop_price(100, signal(), self.config), 95)
        self.assertEqual(stop_price(100, signal(), replace(self.config, stop_method="ATR")), 97)
        self.assertEqual(stop_price(100, signal(), replace(self.config, stop_method="PERCENTAGE")), 95)
        with self.assertRaises(ValueError):
            stop_price(94, signal(), self.config)

    def test_all_rr_targets(self):
        for rr in (1, 1.5, 2, 2.5, 3):
            trade = self.trade([(100, 120, 99, 119)], rr=rr)
            self.assertEqual(trade["target_price"], 100 + 5 * rr)
            self.assertEqual(trade["result_R"], rr)

    def test_mfe_mae_daily_bounds_and_gap_exit(self):
        trade = self.trade([(100, 108, 97, 104), (104, 112, 99, 111)])
        self.assertAlmostEqual(trade["MFE_R"], 2.4)
        self.assertAlmostEqual(trade["MAE_R"], -.6)
        self.assertAlmostEqual(trade["MFE_pct"], .12)
        self.assertAlmostEqual(trade["MAE_pct"], -.03)
        gap = self.trade([(100, 103, 99, 101), (115, 200, 50, 120)])
        self.assertEqual(gap["MFE_R"], 3)
        self.assertAlmostEqual(gap["MAE_R"], -.2)

    def test_costs_slippage_tax_and_minimum_fee(self):
        cfg = replace(self.config, position_shares=10,
                      costs=TradingCosts(True, .001, 20, .003, .001))
        trade = self.trade([(100, 111, 99, 110)], config=cfg)
        self.assertAlmostEqual(trade["gross_return_pct"], .1)
        self.assertEqual(trade["entry_fee"], 20)
        self.assertEqual(trade["exit_fee"], 20)
        expected = (109.89 - 100.1) * 10 - 40 - 109.89 * 10 * .003
        self.assertAlmostEqual(trade["net_pnl"], expected)
        self.assertAlmostEqual(trade["result_R"], expected / 50)

    def test_invalid_entry_and_missing_future_bar(self):
        data = bars([(98, 100, 97, 99), (100, 104, 98, 102), (102, 105, 99, 103)])
        data.iloc[1, data.columns.get_loc("Open")] = float("nan")
        trade, error = simulate_trade(data, signal(), 2, 2, self.config)
        self.assertIsNone(trade)
        self.assertIn("Invalid entry", error)
        data.iloc[1, data.columns.get_loc("Open")] = 100
        data.iloc[2, data.columns.get_loc("High")] = float("nan")
        trade, error = simulate_trade(data, signal(), 2, 2, self.config)
        self.assertEqual(trade["outcome"], "CENSORED")


if __name__ == "__main__":
    unittest.main()
