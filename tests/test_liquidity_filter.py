import copy
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from services.liquidity_filter import (LiquidityConfig, calculate_trading_value, filter_trading_value,
    filter_backtest_signals, format_trading_value, DEFAULT_MIN_TRADING_VALUE)
from services.scanner_entry_service import analyze_scanner_candidates
from services.entry_line_notification_service import build_preview
from tests.test_entry_timing import fixture


def inputs(amounts):
    rows, histories = [], {}
    for i, amount in enumerate(amounts):
        ticker = str(i) + ".TW"
        rows.append(dict(ticker=ticker, signal_date=pd.Timestamp("2026-05-15")))
        histories[ticker] = pd.DataFrame(dict(Close=[50.], Volume=[amount / 50 if amount is not None else None]),
                                        index=pd.DatetimeIndex(["2026-05-15"]))
    return pd.DataFrame(rows), histories


class LiquidityTests(unittest.TestCase):
    def test_150m_passes(self):
        rows, stats = filter_trading_value(*inputs([150e6]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.trading_value.iloc[0], 150e6)

    def test_equal_passes(self):
        self.assertEqual(len(filter_trading_value(*inputs([100e6]))[0]), 1)

    def test_9999m_excluded(self):
        self.assertTrue(filter_trading_value(*inputs([99.99e6]))[0].empty)

    def test_disabled_keeps_low_and_unknown(self):
        result, stats = filter_trading_value(*inputs([10e6, None]), LiquidityConfig(False))
        self.assertEqual(len(result), 2)
        self.assertEqual(result.trading_value_status.iloc[1], "UNKNOWN")
        self.assertTrue(pd.isna(result.trading_value.iloc[1]))
        self.assertEqual(stats["unknown_excluded"], 0)

    def test_custom_and_presets(self):
        for minimum, count in ((50e6, 4), (100e6, 3), (200e6, 2), (250e6, 1), (500e6, 0)):
            result, _ = filter_trading_value(*inputs([50e6, 150e6, 200e6, 300e6]), LiquidityConfig(min_trading_value=minimum))
            self.assertEqual(len(result), count)

    def test_unknown_excluded_at_zero_threshold(self):
        result, stats = filter_trading_value(*inputs([None]), LiquidityConfig(min_trading_value=0))
        self.assertTrue(result.empty)
        self.assertEqual(stats["unknown_excluded"], 1)

    def test_shares_and_lots(self):
        self.assertEqual(calculate_trading_value(dict(Close=50, Volume=3_000_000), "shares")[0], 150e6)
        self.assertEqual(calculate_trading_value(dict(Close=50, Volume=3000), "lots")[0], 150e6)
        with self.assertRaises(ValueError):
            calculate_trading_value(dict(Close=50, Volume=3000), "unknown")

    def test_official_amount_priority_and_unknown_fallback(self):
        row = dict(Close=50, Volume=3_000_000, **{"Trading Value": 123e6})
        self.assertEqual(calculate_trading_value(row), (123e6, "OFFICIAL", "Trading Value"))
        row["Trading Value"] = float("nan")
        self.assertEqual(calculate_trading_value(row)[0], 150e6)
        row["Trading Value"] = 0
        self.assertEqual(calculate_trading_value(row)[0], 0)
        self.assertEqual(calculate_trading_value(dict(Volume=3000))[1], "UNKNOWN")

    def test_invalid_and_zero_volume(self):
        for row in (dict(Close=-1, Volume=100), dict(Close=50, Volume=-1), dict(Close=float("inf"), Volume=1)):
            self.assertEqual(calculate_trading_value(row)[1], "UNKNOWN")
        self.assertEqual(calculate_trading_value(dict(Close=50, Volume=0))[0], 0)

    def test_backtest_exact_signal_day_and_no_future(self):
        signals, histories = inputs([150e6, 50e6])
        for ticker, history in histories.items():
            histories[ticker] = pd.concat([history, pd.DataFrame(dict(Close=[9999.], Volume=[999999999.]), index=pd.DatetimeIndex(["2026-10-02"]))])
        signal_set = dict(signals=signals, histories=histories, stats=dict(signals=2), issues=[])
        saved = copy.deepcopy(signal_set)
        filtered = filter_backtest_signals(signal_set)
        self.assertEqual(filtered["signals"].ticker.tolist(), ["0.TW"])
        self.assertEqual(filtered["signals"].trading_value.iloc[0], 150e6)
        self.assertEqual(filtered["signals"].trading_value_date.iloc[0], "2026-05-15")
        self.assertEqual(filtered["stats"]["signals"], 1)
        pd.testing.assert_frame_equal(signal_set["signals"], saved["signals"])
        for ticker in histories:
            pd.testing.assert_frame_equal(histories[ticker], saved["histories"][ticker])
        historical_only = dict(signal_set, histories={t: h.iloc[:1] for t, h in histories.items()})
        pd.testing.assert_frame_equal(filtered["signals"], filter_backtest_signals(historical_only)["signals"])

    def test_missing_signal_date_never_falls_back_to_today(self):
        rows, histories = inputs([150e6])
        rows["signal_date"] = pd.Timestamp("2020-01-01")
        result, stats = filter_trading_value(rows, histories, date_column="signal_date")
        self.assertTrue(result.empty)
        self.assertEqual(stats["unknown_excluded"], 1)

    def test_latest_bar_for_live_candidates(self):
        rows, histories = inputs([50e6])
        histories["0.TW"].loc[pd.Timestamp("2026-10-02")] = [50, 3_000_000]
        result, _ = filter_trading_value(rows, histories)
        self.assertEqual(result.trading_value.iloc[0], 150e6)
        self.assertEqual(result.trading_value_date.iloc[0], "2026-10-02")

    def test_line_only_receives_liquid_candidates(self):
        event, history = fixture()
        low = dict(event, ticker="9999.TW")
        liquid_history = history.copy()
        liquid_history.loc[liquid_history.index[-1], "Trading Value"] = 187e6
        histories = {event["ticker"]: liquid_history, low["ticker"]: history}
        with patch("yfinance.download", side_effect=AssertionError("No Yahoo")), patch("sqlite3.connect", side_effect=AssertionError("No SQLite")), \
             patch("services.line_bot_service.send_text") as send:
            rows, _ = filter_trading_value(pd.DataFrame([event, low]), histories)
            self.assertEqual(rows.ticker.tolist(), [event["ticker"]])
            entries = analyze_scanner_candidates("impulse_macd", rows, histories)
            preview = build_preview(entries, "impulse_macd")
            self.assertEqual(preview["candidate_count"], 1)
            self.assertIn("成交值：NT$1.87 億", preview["messages"][0])
            self.assertNotIn("9999", preview["messages"][0])
            send.assert_not_called()

    def test_format_and_default(self):
        self.assertEqual(DEFAULT_MIN_TRADING_VALUE, 100_000_000)
        for amount, text in ((50e6, "NT$0.50 億"), (100e6, "NT$1.00 億"), (250e6, "NT$2.50 億"), (500e6, "NT$5.00 億")):
            self.assertEqual(format_trading_value(amount), text)

    def test_controls_filter_locally_and_persist_per_page(self):
        def app_code():
            import streamlit as st
            from src.liquidity_panel import apply_liquidity_controls
            page = st.selectbox("Test page", ["impulse_macd", "bear_flag"])
            result = apply_liquidity_controls(page, st.session_state.rows, st.session_state.histories)
            st.dataframe(result)
        rows, histories = inputs([50e6, 150e6, 300e6])
        app = AppTest.from_function(app_code)
        app.session_state.rows = rows
        app.session_state.histories = histories
        with patch("yfinance.download", side_effect=AssertionError("No download")):
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.dataframe[0].value), 2)
            app.number_input[0].set_value(200_000_000).run()
            self.assertEqual(len(app.dataframe[0].value), 1)
            app.selectbox[0].set_value("bear_flag").run()
            self.assertEqual(app.number_input[0].value, DEFAULT_MIN_TRADING_VALUE)
            app.selectbox[0].set_value("impulse_macd").run()
            self.assertEqual(app.number_input[0].value, 200_000_000)
            app.selectbox[1].set_value("5千萬").run()
            self.assertEqual(app.number_input[0].value, 50_000_000)
            self.assertEqual(len(app.dataframe[0].value), 3)
            app.checkbox[0].uncheck().run()
            self.assertEqual(len(app.dataframe[0].value), 3)

    def test_five_pages_apply_default_filter_and_can_disable(self):
        from tests.test_bull_flag import synthetic, universe
        from tests.test_bull_flag_gap import gap_history
        from tests.test_unfilled_gap import unfilled_history
        from tests.test_backtest_engine import historical_sample
        from tests.test_impulse_macd import prices, STOCK
        from src.impulse_macd import calculate_impulse, historical_cross_events
        raw = prices()
        last = historical_cross_events(calculate_impulse(raw), STOCK)[-1]["signal_index"]
        cases = [("bear_flag", "bull_flag_panel", "render_bull_flag_panel", "cached_histories", synthetic()),
                 ("bear_flag_gap", "bull_flag_gap_panel", "render_gap_panel", "cached_histories", gap_history([120, 118.1])),
                 ("unfilled_gap", "unfilled_gap_panel", "render_unfilled_panel", "load_backtest_histories", unfilled_history()),
                 ("impulse_macd", "impulse_panel", "render_impulse_panel", "load_incremental_histories", raw.iloc[:last+1]),
                 ("bear_flag_backtest", "backtest_panel", "render_backtest_panel", "load_backtest_histories", historical_sample())]
        for scanner, module, render, loader, history in cases:
            with self.subTest(scanner=scanner), ExitStack() as stack:
                stack.enter_context(patch(f"src.{module}.cached_universe", return_value=(universe(), {})))
                download = stack.enter_context(patch(f"src.{module}.{loader}", return_value=({"2330.TW": history}, {})))
                send = stack.enter_context(patch("services.line_bot_service.send_text"))
                if scanner == "bear_flag":
                    stack.enter_context(patch("src.bull_flag_panel.load_news_scores", return_value={}))
                app = AppTest.from_string(f"from src.{module} import {render}\n{render}()")
                app.run(timeout=20)
                app.button[0].click().run(timeout=20)
                self.assertFalse(app.exception)
                self.assertTrue(next(c for c in app.checkbox if c.key == f"_liquidity_{scanner}_enabled").value)
                self.assertTrue(next(b for b in app.button if b.key == "line_push_" + scanner).disabled)
                self.assertEqual(len(app.get("plotly_chart")), 0)
                next(c for c in app.checkbox if c.key == f"_liquidity_{scanner}_enabled").uncheck().run(timeout=20)
                if scanner == "bear_flag_backtest":
                    app.button[0].click().run(timeout=20)
                self.assertFalse(app.exception)
                self.assertGreater(len(app.get("plotly_chart")), 0)
                self.assertEqual(download.call_count, 2 if scanner == "bear_flag_backtest" else 1)
                send.assert_not_called()
