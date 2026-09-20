import unittest

from src.models import WatchlistStock
from src.stock_matcher import match_stock


class StockMatcherTests(unittest.TestCase):
    def setUp(self):
        self.stocks = [
            WatchlistStock("2330", "台積電", ("TSMC",)),
            WatchlistStock("2455", "全新", ("全新光電",)),
        ]

    def test_matches_alias_case_insensitively(self):
        self.assertEqual(match_stock("TSMC raises forecast", None, self.stocks), self.stocks[0])

    def test_matches_standalone_symbol(self):
        self.assertEqual(match_stock("2330 最新消息", None, self.stocks), self.stocks[0])

    def test_does_not_match_symbol_inside_larger_number(self):
        self.assertIsNone(match_stock("成交金額為123300元", None, self.stocks))


if __name__ == "__main__":
    unittest.main()

