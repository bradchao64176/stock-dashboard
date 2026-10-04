"""All LINE traffic is mocked. Tests never send real notifications."""
import copy
import os
import unittest
import uuid
from unittest.mock import Mock, patch

import pandas as pd
import requests
from streamlit.testing.v1 import AppTest

from services.entry_line_notification_service import eligible_candidates, build_preview, send_preview
from services.line_bot_service import send_text
from services.scanner_entry_service import analyze_scanner_candidates, current_backtest_candidates, SCANNER_NAMES
from services.entry_timing_service import calculate_entry_analysis
from src.bull_flag import scan_universe
from src.bull_flag_config import BullFlagConfig
from tests.test_entry_timing import fixture
from tests.test_bull_flag import synthetic, universe


def entry(scanner="impulse_macd", status="PULLBACK_ZONE", ticker="2330.TW"):
    event, history = fixture()
    result = calculate_entry_analysis(event, history)
    result.update(scanner_id=scanner, scanner_name=SCANNER_NAMES[scanner], entry_status=status,
                  ticker=ticker, stock_code=ticker.split(".")[0], stock_name="Test",
                  golden_cross_date=event["golden_cross_date"], cross_zone="ABOVE_ZERO")
    return result


def latest_snapshot():
    history = synthetic(True, 1500)
    history.index = pd.bdate_range(end="2026-10-02", periods=len(history))
    snapshot = scan_universe(universe(), {"2330.TW": history})
    snapshot.update(config=BullFlagConfig(), scan_time="2026-10-02T10:00:00+00:00")
    return snapshot


class ManualLineTests(unittest.TestCase):
    def test_three_statuses_eligible(self):
        for status in ("PULLBACK_ZONE", "BREAKOUT_ZONE", "CROSS_ENTRY"):
            self.assertEqual(len(eligible_candidates(pd.DataFrame([entry(status=status)]), "impulse_macd")), 1)

    def test_all_other_displayed_statuses_included(self):
        for status in ("WATCH", "EXTENDED", "HIGHLY_EXTENDED", "MISSED", "TREND_INVALIDATED", "UNKNOWN"):
            self.assertEqual(len(eligible_candidates(pd.DataFrame([entry(status=status)]), "impulse_macd")), 1)
            self.assertEqual(build_preview(pd.DataFrame([entry(status=status)]), "impulse_macd")["candidate_count"], 1)

    def test_line_does_not_second_guess_displayed_status(self):
        for field, value in (("current_price", 0), ("current_price", -1), ("current_price", float("nan")),
                             ("reference_stop", float("inf")), ("entry_zone_low", None), ("risk_pct", "bad"),
                             ("reference_stop", 200), ("current_price", 120), ("risk_status", "INVALID_RISK_STRUCTURE")):
            row = entry(); row[field] = value
            self.assertEqual(len(eligible_candidates(pd.DataFrame([row]), "impulse_macd")), 1, field)
            self.assertEqual(build_preview(pd.DataFrame([row]), "impulse_macd")["candidate_count"], 1)

    def test_source_isolation(self):
        from src.entry_line_panel import render_entry_line_push_button
        rows = pd.DataFrame([entry("bear_flag")])
        with self.assertRaises(ValueError):
            render_entry_line_push_button("impulse_macd", rows)

    def test_preserve_displayed_order_and_rows(self):
        rows = [entry(status="CROSS_ENTRY", ticker="3.TW"), entry(status="BREAKOUT_ZONE", ticker="2.TW"), entry(ticker="1.TW"), entry(ticker="1.TW")]
        result = eligible_candidates(pd.DataFrame(rows), "impulse_macd")
        self.assertEqual(result.ticker.tolist(), ["3.TW", "2.TW", "1.TW", "1.TW"])

    def test_chunking_13_stocks_and_exact_text(self):
        rows = pd.DataFrame([entry(ticker=str(i) + ".TW") for i in range(13)])
        preview = build_preview(rows, "impulse_macd", now="2026-10-02 22:30")
        self.assertEqual(preview["counts"], [5, 5, 3])
        self.assertEqual(preview["candidate_count"], 13)
        for i, text in enumerate(preview["messages"]):
            self.assertIn(f"第 {i+1}/3 則", text)
            self.assertIn("2026/10/02 22:30", text)
            self.assertIn("$100.00 ～ $103.00", text)
            self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 5000)
        with patch("services.line_bot_service.send_text", return_value={"ok": True, "error": None}) as send:
            self.assertTrue(send_preview(preview, str(uuid.uuid4()))["ok"])
            self.assertEqual([c.args[0] for c in send.call_args_list], preview["messages"])

    def test_each_strategy_metadata(self):
        for scanner, label in (("impulse_macd", "Golden Cross Date"), ("bear_flag", "Flag High"),
                               ("bear_flag_gap", "Gap %"), ("unfilled_gap", "Gap Status"), ("bear_flag_backtest", "Current Breakout Date")):
            text = build_preview(pd.DataFrame([entry(scanner)]), scanner)["messages"][0]
            self.assertIn(SCANNER_NAMES[scanner], text)
            self.assertIn(label, text)

    def test_partial_failure_is_reported(self):
        preview = build_preview(pd.DataFrame([entry(ticker=str(i)) for i in range(11)]), "impulse_macd")
        with patch("services.line_bot_service.send_text", side_effect=[{"ok": True}, {"ok": False, "error": "safe"}]) as send:
            result = send_preview(preview, str(uuid.uuid4()))
        self.assertFalse(result["ok"])
        self.assertEqual(result["stocks_sent"], 5)
        self.assertEqual(send.call_count, 2)

    def test_empty_preview_no_api(self):
        with patch("services.line_bot_service.send_text") as send:
            send_preview(build_preview(pd.DataFrame(), "impulse_macd"), str(uuid.uuid4()))
            send.assert_not_called()

    def test_transport_mocked_and_safe_errors(self):
        with patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "secret-token", "LINE_USER_ID": "secret-user"}), \
             patch("services.line_bot_service.requests.post") as post:
            post.return_value = Mock(status_code=200, headers={})
            token = str(uuid.uuid4())
            self.assertTrue(send_text("message", token)["ok"])
            self.assertEqual(post.call_args.kwargs["headers"]["X-Line-Retry-Key"], token)
            self.assertEqual(post.call_args.kwargs["json"]["messages"], [{"type": "text", "text": "message"}])
            post.return_value = Mock(status_code=401, headers={}, text="secret-token secret-user")
            result = send_text("message", token)
            self.assertFalse(result["ok"])
            self.assertNotIn("secret", str(result))
            post.side_effect = requests.Timeout("secret-token secret-user")
            result = send_text("message", token)
            self.assertFalse(result["ok"])
            self.assertNotIn("secret", str(result))

    def test_transport_missing_credentials_and_length(self):
        with patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "", "LINE_USER_ID": ""}), patch("services.line_bot_service.requests.post") as post:
            self.assertFalse(send_text("hello", str(uuid.uuid4()))["ok"])
            post.assert_not_called()
        with patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "test", "LINE_USER_ID": "test"}), patch("services.line_bot_service.requests.post") as post:
            self.assertFalse(send_text("🔥" * 2501, str(uuid.uuid4()))["ok"])
            post.assert_not_called()

    def test_transport_accepted_retry(self):
        with patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "test", "LINE_USER_ID": "test"}), \
             patch("services.line_bot_service.requests.post", return_value=Mock(status_code=409, headers={"x-line-accepted-request-id": "accepted"})):
            self.assertTrue(send_text("hello", str(uuid.uuid4()))["ok"])

    def test_general_signal_no_fake_golden_cross(self):
        event, history = fixture()
        history.golden_cross = False
        event.update(status="FORMING", price_date=history.index[-1])
        before = history.copy(deep=True)
        with patch("sqlite3.connect", side_effect=AssertionError("No DB IO")), patch("yfinance.download", side_effect=AssertionError("No Yahoo")), patch("services.line_bot_service.send_text") as send:
            result = analyze_scanner_candidates("bear_flag", pd.DataFrame([event]), {event["ticker"]: history})
            self.assertEqual(result.entry_status.iloc[0], "PULLBACK_ZONE")
            self.assertFalse(result.is_cross_entry.iloc[0])
            self.assertIsNone(result.cross_date.iloc[0])
            send.assert_not_called()
        pd.testing.assert_frame_equal(before, history)

    def test_current_backtest_never_uses_historical_trades(self):
        self.assertTrue(current_backtest_candidates({"trades": pd.DataFrame([entry()]), "histories": {}}, now="2026-10-02 22:00")[0].empty)
        snapshot = latest_snapshot()
        saved = copy.deepcopy(snapshot)
        rows, details = current_backtest_candidates(snapshot, now="2026-10-02 22:00")
        self.assertFalse(rows.empty)
        self.assertTrue((rows.status == "BREAKOUT").all())
        self.assertEqual(rows.price_date.iloc[0], pd.Timestamp("2026-10-02"))
        pd.testing.assert_frame_equal(snapshot["patterns"], saved["patterns"])
        self.assertTrue(current_backtest_candidates(snapshot, now="2026-10-05 22:00")[0].empty)
        snapshot["patterns"]["price_date"] = pd.Timestamp("2020-01-01")
        self.assertTrue(current_backtest_candidates(snapshot, now="2026-10-02 22:00")[0].empty)

    def test_zero_candidates_button_disabled(self):
        app = AppTest.from_string('from src.entry_line_panel import render_entry_line_push_button\nimport pandas as pd\nrender_entry_line_push_button("impulse_macd", pd.DataFrame())')
        with patch("services.line_bot_service.send_text") as send:
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button[0].disabled)
            send.assert_not_called()

    def test_failure_display_and_rerun_do_not_retry(self):
        def app_code():
            import streamlit as st
            from src.entry_line_panel import render_entry_line_push_button
            render_entry_line_push_button("impulse_macd", st.session_state.rows)
        app = AppTest.from_function(app_code)
        app.session_state.rows = pd.DataFrame([entry()])
        with patch("services.line_bot_service.send_text", side_effect=RuntimeError("secret-token secret-user")) as send:
            app.run()
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertNotIn("secret", app.error[0].value)
            app.run()
            send.assert_called_once()

    def test_backtest_click_rejects_unbound_preview(self):
        from src.entry_line_panel import _manual_click
        state = {"bear_flag_backtest_entry_results": pd.DataFrame([entry("bear_flag_backtest")])}
        preview = build_preview(state["bear_flag_backtest_entry_results"], "bear_flag_backtest")
        with patch("src.entry_line_panel.st.session_state", state), patch("src.entry_line_panel.send_preview") as send:
            _manual_click("bear_flag_backtest", str(uuid.uuid4()), preview)
            send.assert_not_called()
            self.assertFalse(state["bear_flag_backtest_line_outcome"]["ok"])

    def test_strategy_analysis_does_not_mutate_selection(self):
        from tests.test_bull_flag_gap import gap_history
        from tests.test_unfilled_gap import unfilled_history
        from src.bull_flag_gap import scan_gap_universe
        from src.unfilled_gap import scan_unfilled_universe
        snapshots = [
            ("bear_flag", scan_universe(universe(), {"2330.TW": synthetic(True, 1500)}), "patterns"),
            ("bear_flag_gap", scan_gap_universe(universe(), {"2330.TW": gap_history([120, 121])}), "candidates"),
            ("unfilled_gap", scan_unfilled_universe(universe(), {"2330.TW": unfilled_history()}), "candidates")]
        for scanner, snapshot, field in snapshots:
            saved = copy.deepcopy(snapshot)
            self.assertFalse(snapshot[field].empty)
            with patch("yfinance.download", side_effect=AssertionError("No data request")), \
                 patch("sqlite3.connect", side_effect=AssertionError("No DB")), patch("services.line_bot_service.send_text") as send:
                entries = analyze_scanner_candidates(scanner, snapshot[field], snapshot["details"])
                send.assert_not_called()
            self.assertEqual(entries.ticker.tolist(), snapshot[field].ticker.tolist())
            pd.testing.assert_frame_equal(snapshot[field], saved[field])
            for ticker in snapshot["details"]:
                pd.testing.assert_frame_equal(snapshot["details"][ticker], saved["details"][ticker])

    def test_all_scanners_manual_click_only_and_resend(self):
        def app_code():
            import streamlit as st
            from src.entry_line_panel import render_entry_line_push_button
            render_entry_line_push_button(st.session_state.scanner, st.session_state.rows)
        for scanner in SCANNER_NAMES:
            with self.subTest(scanner=scanner), patch("services.line_bot_service.send_text", return_value={"ok": True}) as send, \
                 patch("src.entry_line_panel.current_backtest_candidates", return_value=(pd.DataFrame([entry(scanner)]), {})):
                app = AppTest.from_function(app_code)
                app.session_state.scanner = scanner
                rows = pd.DataFrame([entry(scanner)])
                app.session_state.rows = rows
                app.session_state[scanner + "_entry_results"] = rows
                app.run(); app.run()
                self.assertFalse(app.exception)
                send.assert_not_called()
                text = app.text[0].value
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(send.call_args.args[0], text)
                first_key = send.call_args.args[1]
                app.run()
                self.assertEqual(send.call_count, 1)
                app.button[0].click().run()
                self.assertEqual(send.call_count, 2)
                self.assertNotEqual(send.call_args.args[1], first_key)

    def test_same_event_consumed_once(self):
        from src.entry_line_panel import _manual_click, _fingerprint
        rows = pd.DataFrame([entry()])
        state = {"impulse_macd_entry_results": rows}
        preview = build_preview(rows, "impulse_macd")
        preview["analysis_fingerprint"] = _fingerprint(rows)
        token = str(uuid.uuid4())
        with patch("src.entry_line_panel.st.session_state", state), patch("src.entry_line_panel.send_preview", return_value={"ok": True}) as send:
            _manual_click("impulse_macd", token, preview)
            _manual_click("impulse_macd", token, preview)
            send.assert_called_once()

    def test_saved_analysis_reused_on_send_no_db_no_download(self):
        def app_code():
            import streamlit as st
            from src.entry_line_panel import render_scanner_entry_section
            render_scanner_entry_section("impulse_macd", st.session_state.snapshot["candidates"], st.session_state.snapshot)
        event, data = fixture()
        snapshot = dict(candidates=pd.DataFrame([event]), details={event["ticker"]: data})
        app = AppTest.from_function(app_code)
        app.session_state.snapshot = snapshot
        with patch("services.line_bot_service.send_text", return_value={"ok": True}) as send:
            app.run()
            self.assertFalse(app.exception)
            send.assert_not_called()
            with patch("src.entry_line_panel.analyze_scanner_candidates", side_effect=AssertionError("No recalculation")), \
                 patch("sqlite3.connect", side_effect=AssertionError("No DB")), patch("yfinance.download", side_effect=AssertionError("No Yahoo")):
                app.button[0].click().run()
                self.assertFalse(app.exception)
                send.assert_called_once()

    def test_existing_page_load_scan_and_filter_tests_never_send(self):
        from tests.test_bull_flag_panel import BullFlagPanelTests
        from tests.test_bull_flag_gap_panel import GapPanelTests
        from tests.test_unfilled_gap_panel import UnfilledPanelTests
        from tests.test_backtest_storage_ui import StorageAndUITests
        from tests.test_impulse_macd import ImpulseTests
        methods = [BullFlagPanelTests().test_scan_filter_and_detail_do_not_download_again,
                   GapPanelTests().test_scan_filters_chart_and_navigation_without_redownload,
                   UnfilledPanelTests().test_defaults_scan_and_status_filter_no_redownload,
                   StorageAndUITests().test_page_scan_and_display_controls_do_not_download,
                   ImpulseTests().test_ui_scans_through_service_and_filter_does_not_download]
        with patch("services.line_bot_service.send_text") as send:
            for method in methods:
                method()
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
