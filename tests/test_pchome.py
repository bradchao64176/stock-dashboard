import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup

from services.institutional_analysis import analyze_institutions, combine_stock_scores
from services.institutional_history import save_history
from services.pchome_scraper import PChomeParseError, fetch_stock, number, parse_stock, stock_url


FIXTURE = Path(__file__).parent / "fixtures" / "pchome_2409.html"


class PChomeTests(unittest.TestCase):
    def setUp(self):
        self.html = FIXTURE.read_text(encoding="utf-8")
        self.stock = parse_stock(self.html, "2409")

    def test_quote_and_all_institutional_tables(self):
        self.assertEqual(self.stock["name"], "友達")
        self.assertEqual(self.stock["price"], 30.35)
        self.assertEqual(self.stock["volume"], 348056)
        self.assertEqual(self.stock["change_percent"], 1.17)
        self.assertEqual(self.stock["foreign"]["net"], -52163)
        self.assertEqual(self.stock["investment_trust"]["ownership_percent"], 0.13)
        self.assertEqual(self.stock["dealer"]["shares_held"], 516192)
        self.assertEqual(self.stock["institutional_total"]["net"], -45063)
        # Published rounded totals differ from a simple subtraction; preserve them.
        self.assertEqual(self.stock["history"]["dealer"][1]["net"], 2322)
        json.dumps(self.stock, allow_nan=False)

    def test_tables_can_be_reordered_with_unrelated_tables_inserted(self):
        soup = BeautifulSoup(self.html, "html.parser")
        tables = [table.extract() for table in soup.find_all("table") if "買賣超張數" in table.get_text()]
        for table in reversed(tables):
            soup.append(table)
        soup.insert(0, BeautifulSoup("<table><tr><th>Other</th></tr><tr><td>9</td></tr></table>", "html.parser"))
        result = parse_stock(str(soup), "2409")
        self.assertEqual(result["history"], self.stock["history"])

    def test_stock_validation_and_leading_zeros(self):
        self.assertTrue(stock_url(" 0050 ").endswith("sid0050.html"))
        self.assertTrue(stock_url("00981a").endswith("sid00981A.html"))
        for value in ("", "../2330", "2330.TW", "１２３４", "123", "1234567"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                stock_url(value)

    def test_blocked_wrong_stock_missing_price_and_missing_tables(self):
        for html, code in (("<html>Access denied</html>", "2409"), (self.html, "2330"),
                           (self.html.replace("30.35</span>", "--</span>"), "2409")):
            with self.assertRaises(PChomeParseError):
                parse_stock(html, code)
        soup = BeautifulSoup(self.html, "html.parser")
        for table in soup.find_all("table"):
            if "買賣超張數" in table.get_text():
                table.decompose()
        result = parse_stock(str(soup), "2409")
        self.assertIsNone(result["foreign"])
        self.assertIsNone(analyze_institutions(result)["score"])
        self.assertTrue(result["warnings"])

    def test_numeric_missing_and_non_finite(self):
        for value in ("--", "N/A", "NaN", "inf", "not a price", ""):
            self.assertIsNone(number(value))
        self.assertEqual(number("53,223"), 53223)
        self.assertEqual(number("−1.17%"), -1.17)
        self.assertEqual(number("▼-3.5"), -3.5)
        self.assertEqual(number("0"), 0)

    @patch("services.pchome_scraper.requests.Session")
    def test_fetch_follows_known_loading_form(self, session_class):
        session = session_class.return_value.__enter__.return_value
        session.get.return_value.content = b'<form id="submit_form" action=""><input name="is_check" value="1"></form>'
        session.post.return_value.content = self.html.encode("utf-8")
        result = fetch_stock("2409")
        self.assertEqual(result["stock_id"], "2409")
        session.get.assert_called_once_with(stock_url("2409"), timeout=15)
        session.post.assert_called_once_with(stock_url("2409"), data={"is_check": "1"}, timeout=15)
        session.get.return_value.raise_for_status.assert_called_once()
        session.post.return_value.raise_for_status.assert_called_once()

    @patch("services.pchome_scraper.requests.Session")
    def test_errors_propagate_and_foreign_form_is_not_followed(self, session_class):
        session = session_class.return_value.__enter__.return_value
        session.get.side_effect = requests.Timeout("timeout")
        with self.assertRaises(requests.Timeout):
            fetch_stock("2409")
        session.get.side_effect = None
        session.get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
        with self.assertRaises(requests.HTTPError):
            fetch_stock("2409")
        session.get.return_value.raise_for_status.side_effect = None
        session.get.return_value.content = b'<form id="submit_form" action="https://example.com"><input name="is_check" value="1"></form>'
        with self.assertRaises(PChomeParseError):
            fetch_stock("2409")
        session.post.assert_not_called()

    def test_indicators_require_full_windows_and_matching_volume_date(self):
        analysis = analyze_institutions(self.stock)
        foreign = analysis["indicators"]["foreign"]
        self.assertEqual(foreign["net_5d"], -72265)
        self.assertIsNone(foreign["net_10d"])
        self.assertEqual(analysis["indicators"]["dealer"]["consecutive_buy_days"], 3)
        self.assertIsNone(analysis["institutional_buy_ratio"])
        analysis = analyze_institutions(self.stock, {"2026-09-18": 348056})
        self.assertAlmostEqual(analysis["institutional_buy_ratio"], -45063 / 348056)
        self.assertIsNone(analyze_institutions(self.stock, {"2026-09-17": 348056})["institutional_buy_ratio"])
        self.assertIsNone(analyze_institutions(self.stock, {"2026-09-18": 0})["institutional_buy_ratio"])

    def test_twenty_day_history_score_bounds_and_unknown_streak(self):
        for sign, expected in ((1, 100), (-1, 0), (0, 50)):
            stock = deepcopy(self.stock)
            for key in stock["history"]:
                stock["history"][key] = [dict(stock[key], date=(date(2026, 9, 18) - timedelta(days=i)).isoformat(),
                                              net=sign * 10) for i in range(20)]
                stock[key] = stock["history"][key][0]
            analysis = analyze_institutions(stock)
            self.assertEqual(analysis["score"], expected)
            self.assertEqual(analysis["indicators"]["foreign"]["net_20d"], sign * 200)
            self.assertEqual(analysis["indicators"]["foreign"]["net_10d"], sign * 100)
        stock["history"]["foreign"][0]["net"] = None
        indicator = analyze_institutions(stock)["indicators"]["foreign"]
        self.assertIsNone(indicator["net_5d"])
        self.assertIsNone(indicator["consecutive_buy_days"])

    def test_weighted_combination_missing_components_and_validation(self):
        result = combine_stock_scores({"institutional": 80, "news": 20})
        self.assertAlmostEqual(result["score"], 53.33)
        self.assertEqual(result["coverage"], 0.45)
        self.assertEqual(result["missing"], ["fundamental", "technical"])
        self.assertEqual(combine_stock_scores({"institutional": 80}, {"institutional": 1})["score"], 80)
        self.assertIsNone(combine_stock_scores({})["score"])
        for weights in ({"news": 0}, {"news": -1}, {"news": float("nan")}, {"typo": 1}):
            with self.assertRaises(ValueError):
                combine_stock_scores({}, weights)
        with self.assertRaises(ValueError):
            combine_stock_scores({"news": 101})

    def test_history_merges_corrects_deduplicates_and_does_not_bridge_gaps(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "history.db"
            save_history(self.stock, database)
            newer = deepcopy(self.stock)
            for key, rows in newer["history"].items():
                rows.insert(0, dict(rows[0], date="2026-09-21", net=123))
                rows.pop()
                rows[1]["net"] = 42
            combined = save_history(newer, database)
            self.assertEqual(len(combined["history"]["foreign"]), 6)
            self.assertEqual(combined["history"]["foreign"][1]["net"], 42)
            self.assertEqual(len(save_history(newer, database)["history"]["foreign"]), 6)
            other = deepcopy(newer)
            other["stock_id"] = "2330"
            self.assertEqual(len(save_history(other, database)["history"]["foreign"]), 5)
            gap = deepcopy(newer)
            for key in gap["history"]:
                gap["history"][key] = [dict(gap[key], date="2026-10-01")]
            result = save_history(gap, database)
            self.assertEqual(len(result["history"]["foreign"]), 1)
            self.assertTrue(any("do not overlap" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
