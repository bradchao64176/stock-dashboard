import re
import unittest
import uuid
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from services.entry_line_notification_service import get_line_eligible_candidates, build_preview
from services.scanner_entry_service import SCANNER_NAMES
from tests.test_manual_entry_line import entry


def scenario(scanner):
    statuses = ["PULLBACK_ZONE", "BREAKOUT_ZONE", "CROSS_ENTRY", "WATCH", "EXTENDED", "HIGHLY_EXTENDED", "TREND_INVALIDATED"]
    rows = [dict(entry(scanner, status, code), stock_code=code) for code, status in zip("ABCDEFGHIJKLMNOPQR", (statuses * 3)[:18])]
    # C is deliberately outside its zone: LINE must consume the displayed
    # status, not duplicate the Entry engine's conditions.
    rows[2]["current_price"] = 123.45
    return pd.DataFrame(rows)


class EntryLineSourceTests(unittest.TestCase):
    def test_same_table_preview_payload_all_five_pages(self):
        def app_code():
            import streamlit as st
            from src.entry_line_panel import render_scanner_entry_section
            render_scanner_entry_section(st.session_state.page, st.session_state.raw["candidates"], st.session_state.raw)
        for scanner in SCANNER_NAMES:
            with self.subTest(scanner=scanner):
                rows = scenario(scanner)
                app = AppTest.from_function(app_code)
                app.session_state.page = scanner
                app.session_state.raw = dict(candidates=pd.DataFrame([dict(ticker="RAW_ONLY")]), details={})
                app.session_state["liquidity_" + scanner + "_minimum"] = 100_000_000
                with patch("src.entry_line_panel.analyze_scanner_candidates", return_value=rows) as analyze, \
                     patch("services.line_bot_service.send_text", return_value={"ok": True}) as send:
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertEqual(app.dataframe[0].value.stock_code.tolist(), list("ABCDEFGHIJKLMNOPQR"))
                    stored = app.session_state[scanner + "_entry_results"]
                    eligible = set(get_line_eligible_candidates(stored).stock_code)
                    self.assertEqual(eligible, set("ABCDEFGHIJKLMNOPQR"))
                    packet = app.session_state[scanner + "_line_preview"]["preview"]
                    self.assertEqual(packet["candidate_count"], 18)
                    self.assertEqual(set(packet["stock_codes"]), eligible)
                    metadata = dict(app.session_state[scanner + "_entry_metadata"])
                    self.assertEqual(metadata["candidate_count"], 18)
                    self.assertEqual(metadata["trading_value_threshold"], 100_000_000)
                    self.assertIn("18", app.button[0].label)
                    self.assertEqual(app.text[0].value, packet["messages"][0])
                    send.assert_not_called()
                    analyze.side_effect = AssertionError("No Entry recalculation on send")
                    with patch("src.entry_line_panel.current_backtest_candidates", side_effect=AssertionError("No raw scanner lookup")), \
                         patch("services.liquidity_filter.filter_trading_value", side_effect=AssertionError("No liquidity filtering")), \
                         patch("yfinance.download", side_effect=AssertionError("No Yahoo")), \
                         patch("sqlite3.connect", side_effect=AssertionError("No SQLite")):
                        app.button[0].click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual(send.call_count, len(packet["messages"]))
                    self.assertEqual([call.args[0] for call in send.call_args_list], packet["messages"])
                    actual = "\n".join(call.args[0] for call in send.call_args_list)
                    actual_codes = set(re.findall(r" ([A-R]) Test", actual))
                    self.assertEqual(actual_codes, eligible)
                    self.assertNotIn("RAW_ONLY", actual)
                    self.assertIn("123.45", actual)
                    self.assertEqual(app.session_state[scanner + "_line_outcome"]["stocks_sent"], 18)
                    self.assertEqual(dict(app.session_state[scanner + "_entry_metadata"]), metadata)

    def test_replaced_snapshot_rejects_old_preview_without_scanner(self):
        from src.entry_line_panel import _manual_click, _fingerprint
        rows = scenario("impulse_macd")
        preview = build_preview(rows, "impulse_macd")
        preview["analysis_fingerprint"] = _fingerprint(rows)
        changed = rows.copy(); changed.loc[0, "entry_status"] = "WATCH"
        state = {"impulse_macd_entry_results": changed}
        with patch("src.entry_line_panel.st.session_state", state), patch("src.entry_line_panel.send_preview") as send:
            _manual_click("impulse_macd", str(uuid.uuid4()), preview)
            send.assert_not_called()
            self.assertFalse(state["impulse_macd_line_outcome"]["ok"])

    def test_all_rows_minimal_frame(self):
        rows = pd.DataFrame(dict(stock_code=list("ABCD"), entry_status=["PULLBACK_ZONE", "BREAKOUT_ZONE", "CROSS_ENTRY", "UNKNOWN"]))
        self.assertEqual(get_line_eligible_candidates(rows).stock_code.tolist(), list("ABCD"))
