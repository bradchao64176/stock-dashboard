import unittest
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd

from services.taiwan_universe import normalize_companies, fetch_taiwan_universe
from services.yahoo_history import download_histories, split_history, completed_daily_bars
from src.bull_flag import (validate_history, add_indicators, detect_patterns,
                           scan_universe, filter_candidates)
from src.bull_flag_config import BullFlagConfig, ScoreWeights


def synthetic(breakout=False, volume=600):
    close = np.concatenate([np.linspace(75, 90, 130), np.linspace(90, 120, 20),
                            119 - np.arange(8) * 0.4, [118 if breakout else 115.8]])
    data = pd.DataFrame({"Open": close - 0.2, "High": close + 1, "Low": close - 1,
                         "Close": close, "Adj Close": close, "Volume": 1000.0},
                        index=pd.bdate_range("2025-01-01", periods=len(close)))
    data.iloc[-9:-1, data.columns.get_loc("Volume")] = 400
    data.iloc[-1, data.columns.get_loc("Volume")] = volume
    return data


def universe():
    return pd.DataFrame([dict(stock_code="2330", stock_name="台積電", market="TWSE", ticker="2330.TW")])


class BullFlagTests(unittest.TestCase):
    config = BullFlagConfig(min_flag_days=8, max_flag_days=8)

    def patterns(self, data, config=None):
        return detect_patterns(add_indicators(validate_history(data)), config or self.config)

    def test_valid_descending_flag_and_scores(self):
        result = self.patterns(synthetic())[0]
        self.assertEqual(result["status"], "FORMING")
        self.assertLess(result["high_slope"], 0)
        self.assertLess(result["low_slope"], 0)
        self.assertAlmostEqual(result["high_slope"], -0.4)
        self.assertGreaterEqual(result["bull_flag_score"], 60)
        self.assertLessEqual(result["bull_flag_score"], 100)
        self.assertAlmostEqual(result["bull_flag_score"], sum(value for key, value in result.items()
                               if key.startswith("score_")), places=1)

    def test_breakout_holdout_and_volume(self):
        forming = self.patterns(synthetic())[0]
        result = self.patterns(synthetic(True, 1500))[0]
        self.assertEqual(result["status"], "BREAKOUT")
        self.assertEqual(result["high_slope"], forming["high_slope"])
        self.assertEqual(result["upper_flag_trendline"], forming["upper_flag_trendline"])
        self.assertEqual(result["score_breakout"], 10)
        self.assertGreater(result["close"], result["upper_flag_trendline"])

    def test_breakout_without_volume_remains_visible(self):
        result = self.patterns(synthetic(True, 500))[0]
        self.assertEqual(result["status"], "FORMING")
        self.assertTrue(result["price_breakout"])
        self.assertEqual(result["score_breakout"], 0)

    def test_volume_contraction(self):
        data = synthetic()
        result = self.patterns(data)[0]
        self.assertAlmostEqual(result["volume_ratio"], 0.4)
        data.iloc[-9:-1, data.columns.get_loc("Volume")] = 1200
        expanded = self.patterns(data)[0]
        self.assertEqual(expanded["score_volume"], 0)
        self.assertGreater(result["bull_flag_score"], expanded["bull_flag_score"])

    def test_uptrend_without_flag_downtrend_and_sideways(self):
        for close in (np.linspace(70, 140, 159), np.linspace(140, 70, 159), np.repeat(100.0, 159)):
            with self.subTest(first=close[0], last=close[-1]):
                data = synthetic()
                for column in ("Open", "High", "Low", "Close", "Adj Close"):
                    data[column] = close + (1 if column == "High" else -1 if column == "Low" else 0)
                self.assertEqual(self.patterns(data), [])

    def test_excessive_pullback(self):
        data = synthetic()
        data.iloc[-2, data.columns.get_loc("Low")] = 100
        self.assertEqual(self.patterns(data), [])

    def test_missing_insufficient_duplicate_and_invalid_values(self):
        samples = [synthetic().iloc[:40], synthetic().drop(columns="Volume"), pd.DataFrame()]
        for column, value in (("Close", np.nan), ("High", np.inf), ("Volume", -1), ("Low", 1000)):
            data = synthetic()
            data.iloc[-1, data.columns.get_loc(column)] = value
            samples.append(data)
        samples.append(pd.concat([synthetic(), synthetic().tail(1)]))
        for data in samples:
            with self.subTest(shape=data.shape), self.assertRaises(ValueError):
                validate_history(data)

    def test_indicators_and_adjustment(self):
        data = synthetic()
        result = add_indicators(data)
        self.assertAlmostEqual(result.MA20.iloc[-1], data.Close.tail(20).mean())
        self.assertAlmostEqual(result.return_5d.iloc[-1], data.Close.iloc[-1] / data.Close.iloc[-6] - 1)
        split = data.copy()
        split.loc[split.index[:100], ["Open", "High", "Low", "Close"]] *= 2
        pd.testing.assert_series_equal(add_indicators(split).Close, result.Close)

    def test_configurable_thresholds(self):
        self.assertEqual(self.patterns(synthetic(), replace(self.config, min_flagpole_return=0.8)), [])
        with self.assertRaises(ValueError):
            BullFlagConfig(weights=ScoreWeights(uptrend=30))
        with self.assertRaises(ValueError):
            BullFlagConfig(min_flag_days=20, max_flag_days=5)

    def test_failure_isolation_and_filtering(self):
        stocks = pd.concat([universe(), universe().assign(ticker="bad.TW"),
                            universe().assign(ticker="missing.TWO")], ignore_index=True)
        result = scan_universe(stocks, {"2330.TW": synthetic(), "bad.TW": synthetic().iloc[:20]}, self.config)
        self.assertEqual(result["stats"], dict(total=3, downloaded=2, analyzed=1,
                         candidates=1, forming=1, breakout=0, skipped=1, errors=1))
        self.assertEqual(len(result["issues"]), 2)
        self.assertEqual(len(filter_candidates(result["patterns"])), 1)
        self.assertTrue(filter_candidates(result["patterns"], market="TPEx").empty)
        self.assertTrue(filter_candidates(result["patterns"], status="BREAKOUT").empty)
        self.assertTrue(filter_candidates(result["patterns"], flag_days=(5, 7)).empty)

    def test_nonparallel_channel(self):
        data = synthetic()
        data.iloc[-9:-1, data.columns.get_loc("Low")] -= np.arange(8) * 0.9
        self.assertEqual(self.patterns(data), [])


class DataServicesTests(unittest.TestCase):
    def test_universe_schema_and_security_exclusions(self):
        payload = [{"公司代號": code, "公司簡稱": "公司"}
                   for code in ("2330", "0050", "00632R", "2330A", "123456", "9103", "2330")]
        result = normalize_companies(payload, "TWSE")
        self.assertEqual(result.ticker.tolist(), ["2330.TW"])
        otc = normalize_companies([{"SecuritiesCompanyCode": "5483", "CompanyAbbreviation": "中美晶"}], "TPEx")
        self.assertEqual(otc.ticker.tolist(), ["5483.TWO"])
        with self.assertRaises(ValueError):
            normalize_companies([{"renamed": "2330"}], "TWSE")

    def test_partial_universe_failure(self):
        with patch("services.taiwan_universe.requests.Session") as session:
            response = session.return_value.__enter__.return_value.get.return_value
            response.json.side_effect = [[{"公司代號": "2330", "公司簡稱": "台積電"}], ValueError("bad JSON")]
            frame, errors = fetch_taiwan_universe()
        self.assertEqual(len(frame), 1)
        self.assertIn("TPEx", errors)

    def test_yahoo_shapes_and_retry_failed_only(self):
        frame = pd.concat({"2330.TW": synthetic()}, axis=1)
        pd.testing.assert_frame_equal(split_history(frame.swaplevel(axis=1), "2330.TW", 2), synthetic())
        with patch("services.yahoo_history.time.sleep"), patch("services.yahoo_history.yf.download") as download:
            download.side_effect = [frame, synthetic()]
            result, errors = download_histories(["2330.TW", "5483.TWO"])
        self.assertEqual(set(result), {"2330.TW", "5483.TWO"})
        self.assertFalse(errors)
        self.assertEqual(download.call_args_list[1].args[0], ["5483.TWO"])

    def test_all_download_failures_do_not_raise(self):
        with patch("services.yahoo_history.yf.download", side_effect=RuntimeError("network")):
            histories, errors = download_histories(["2330.TW"], retries=0)
        self.assertFalse(histories)
        self.assertIn("2330.TW", errors)

    def test_unfinished_session_excluded(self):
        data = synthetic()
        date = data.index[-1]
        morning = datetime(date.year, date.month, date.day, 10, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(len(completed_daily_bars(data, morning)), len(data) - 1)
        self.assertEqual(len(completed_daily_bars(data, morning.replace(hour=14))), len(data))


if __name__ == "__main__":
    unittest.main()
