import unittest
from dataclasses import replace
import pandas as pd
from smc.config import SMCConfig
from smc.calendar import TradingCalendar, parse_year
from smc.data import prepare_daily
from smc.timeframes import weekly_bars
from smc.pivots import confirmed_pivots
from smc.market_structure import analyze_structure
from smc.entry_analysis import analyze_entry


def fixture(reverse=False):
    close = [12,15,12,10,13,10,8,11,9,7,10,8,13,12,15,13,12,14,16]
    if reverse:
        close = [30-value for value in close]
    idx = pd.bdate_range("2026-01-05", periods=len(close))
    return pd.DataFrame(dict(Open=[v+.1 for v in close], High=[v+.4 for v in close],
                             Low=[v-.4 for v in close], Close=close, Volume=2_000_000,
                             valid_bar=True, trading_value=200_000_000), index=idx)


CFG = SMCConfig(swing_left=1, swing_right=1, internal_left=1, internal_right=1,
                volume_period=2, min_volume_ratio=0, min_traded_value=0, breakout_buffer=0)
CAL = TradingCalendar(frozenset([2025, 2026, 2027]), frozenset())


class SMCEngineTests(unittest.TestCase):
    def test_choch_then_bos_both_directions(self):
        for reverse, direction in ((False, "BULLISH"), (True, "BEARISH")):
            data = fixture(reverse)
            result = analyze_structure(data, "2330.TW", CFG)
            events = [e for e in result["events"] if e["direction"] == direction]
            self.assertEqual([e["kind"] for e in events], ["CHOCH", "BOS"])
            self.assertEqual(events[0]["position"], 12)
            self.assertEqual(events[1]["position"], 18)
            self.assertEqual(events[1]["parent_id"], events[0]["signal_id"])
            self.assertNotEqual(events[0]["signal_id"], events[1]["signal_id"])

    def test_prefix_stability_no_future_or_repainting(self):
        data = fixture()
        full = analyze_structure(data, "2330.TW", CFG)
        for end in range(1, len(data)+1):
            prefix = analyze_structure(data.iloc[:end], "2330.TW", CFG)
            self.assertEqual(prefix["events"], [e for e in full["events"] if e["position"] < end])
            self.assertEqual(prefix["states"], full["states"][:end])
            self.assertEqual(prefix["pivots"], [p for p in full["pivots"] if p["confirmed_position"] < end])

    def test_pivot_confirmation_delay_and_equal_highs(self):
        data = fixture()
        self.assertFalse(list(confirmed_pivots(data.iloc[:2], 1, 1)))
        pivots = list(confirmed_pivots(data.iloc[:3], 1, 1))
        self.assertEqual(pivots[0].pivot_time, data.index[1])
        self.assertEqual(pivots[0].confirmed_at, data.index[2])
        data.loc[data.index[2], "High"] = data.High.iloc[1]
        self.assertFalse(list(confirmed_pivots(data.iloc[:3], 1, 1)))

    def test_wick_is_not_close_breakout_and_no_duplicate(self):
        data = fixture().iloc[:13].copy()
        data.loc[data.index[-1], "Close"] = 10
        self.assertFalse([e for e in analyze_structure(data, "X", CFG)["events"] if e["kind"] == "CHOCH"])
        events = analyze_structure(fixture(), "X", CFG)["events"]
        self.assertEqual(len(events), len({e["signal_id"] for e in events}))

    def test_missing_bar_resets_structure(self):
        data = fixture(); data.loc[data.index[11], "valid_bar"] = False
        self.assertFalse([e for e in analyze_structure(data, "X", CFG)["events"] if e["kind"] == "CHOCH"])

    def test_completed_daily_and_weekly(self):
        data = fixture()
        daily = prepare_daily(data, "2026-01-09 13:00+08:00", CAL)
        self.assertEqual(daily.index[-1], pd.Timestamp("2026-01-08"))
        self.assertTrue(weekly_bars(daily, "2026-01-09 13:00+08:00", CAL).empty)
        daily = prepare_daily(data, "2026-01-09 14:00+08:00", CAL)
        week = weekly_bars(daily, "2026-01-09 14:00+08:00", CAL)
        self.assertEqual(week.Volume.iloc[0], 10_000_000)
        self.assertEqual(week.Open.iloc[0], data.Open.iloc[0])
        self.assertEqual(week.Close.iloc[0], data.Close.iloc[4])
        self.assertTrue(week.valid_bar.iloc[0])

    def test_calendar_information_days_are_open(self):
        payload = dict(stat="ok", queryYear=2026, data=[["2026-01-01", "Holiday", ""], ["2026-01-02", "國曆新年開始交易日", ""]])
        self.assertEqual(parse_year(payload, 2026), {pd.Timestamp("2026-01-01")})

    def test_entry_bos_wait_then_trigger_and_invalidation(self):
        data = fixture(); result = analyze_structure(data, "X", CFG)
        signal = next(e for e in result["events"] if e["kind"] == "CHOCH")
        cfg = replace(CFG, bos_confirmation=True, entry_mode="BOS")
        prefix = analyze_structure(data.iloc[:16], "X", cfg)
        self.assertEqual(analyze_entry(data.iloc[:16], signal, prefix, cfg)["entry_status"], "WAIT")
        entry = analyze_entry(data, signal, result, cfg)
        self.assertEqual(entry["entry_status"], "TRIGGERED")
        self.assertLess(entry["stop_loss"], entry["entry_price"])
        self.assertGreater(entry["target_price"], entry["entry_price"])
        bad = data.copy(); bad.loc[bad.index[-1], "Low"] = 1
        self.assertEqual(analyze_entry(bad, signal, result, cfg)["entry_status"], "INVALIDATED")
