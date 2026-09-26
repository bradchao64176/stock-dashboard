import unittest
import pandas as pd

from backtesting.metrics import summarize, equity_curve


def trades():
    return pd.DataFrame(dict(
        outcome=["LOSS", "WIN", "TIMEOUT", "LOSS"], result_R=[-1, 2, .5, -1],
        net_pnl=[-100, 200, 50, -100], net_return_pct=[-.01, .02, .005, -.01],
        holding_days=[2, 3, 20, 4], same_bar_ambiguous=[False] * 4,
        MFE_R=[.2, 2.1, .8, .5], MAE_R=[-1, -.3, -.2, -1], ticker=["2330.TW"] * 4,
        signal_date=pd.date_range("2025-01-01", periods=4),
        entry_date=pd.date_range("2025-01-02", periods=4),
        exit_date=pd.date_range("2025-01-05", periods=4)))


class MetricsTests(unittest.TestCase):
    def test_expectancy_profit_factor_and_denominators(self):
        summary = summarize(trades(), 2, total_signals=6, starting_capital=1000)
        self.assertEqual(summary["expectancy"], .125)
        self.assertEqual(summary["profit_factor"], 1.25)
        self.assertEqual(summary["win_rate"], .25)
        self.assertEqual(summary["timeout_rate"], .25)
        self.assertEqual(summary["break_even_win_rate"], 1 / 3)
        self.assertEqual(summary["total_signals"], 6)

    def test_drawdown_includes_initial_capital(self):
        curve = equity_curve(trades(), 1000)
        self.assertEqual(curve.equity.tolist(), [1000, 900, 1100, 1150, 1050])
        self.assertAlmostEqual(summarize(trades(), 2, starting_capital=1000)["maximum_drawdown"], .1)
        self.assertEqual(curve.cumulative_R.iloc[-1], .5)

    def test_excluded_and_censored_not_losses(self):
        data = trades()
        data.loc[0, "outcome"] = "AMBIGUOUS"
        data.loc[0, "same_bar_ambiguous"] = True
        data.loc[3, "outcome"] = "CENSORED"
        summary = summarize(data, 2)
        self.assertEqual(summary["evaluated_trades"], 2)
        self.assertEqual(summary["win_rate"], .5)
        self.assertEqual(summary["expectancy"], 1.25)
        self.assertEqual(summary["censored"], 1)

    def test_empty_metrics_are_not_fake_zeros(self):
        summary = summarize(pd.DataFrame(), 2)
        self.assertTrue(pd.isna(summary["win_rate"]))
        self.assertTrue(pd.isna(summary["expectancy"]))


if __name__ == "__main__":
    unittest.main()
