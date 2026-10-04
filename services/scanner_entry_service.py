"""Adapters from existing scanner snapshots to the shared Entry Timing engine."""
import pandas as pd

from services.entry_timing_service import calculate_entry_analysis
from src.impulse_macd import ImpulseConfig

SCANNER_NAMES = {
    "impulse_macd": "Impulse MACD 黃金交叉選股",
    "bear_flag": "台股下降旗形選股",
    "bear_flag_gap": "下降旗形多方缺口突破",
    "unfilled_gap": "多方未回補缺口選股",
    "bear_flag_backtest": "下降旗形策略回測",
}


def analyze_scanner_candidates(scanner_id, candidates, details, impulse_config=ImpulseConfig()):
    if scanner_id not in SCANNER_NAMES:
        raise ValueError("Unknown scanner")
    rows = []
    for source in candidates.to_dict("records"):
        candidate = dict(source)
        history = details.get(candidate["ticker"])
        if scanner_id == "impulse_macd":
            kind = "IMPULSE"
        else:
            kind = "SIGNAL"
            if scanner_id in ("bear_flag", "bear_flag_backtest"):
                candidate["signal_date"] = candidate.get("price_date") if candidate.get("status") == "BREAKOUT" else None
            elif scanner_id == "bear_flag_gap":
                # Both breakout and gap must be known before the combined signal.
                dates = [pd.Timestamp(candidate[k]) for k in ("breakout_date", "gap_date") if pd.notna(candidate.get(k))]
                candidate["signal_date"] = max(dates) if dates else None
            else:
                candidate["signal_date"] = candidate.get("gap_date")
        result = calculate_entry_analysis(candidate, history, impulse_config=impulse_config, candidate_kind=kind)
        # Metadata remains separate from calculated values. Never replace source rows.
        result["scanner_id"] = scanner_id
        result["scanner_name"] = SCANNER_NAMES[scanner_id]
        for field in ("trading_value", "trading_value_status", "trading_value_source", "trading_value_date", "passes_trading_value_filter", "成交值",
                      "golden_cross_date", "cross_zone", "upper_flag_trendline", "lower_flag_trendline",
                      "breakout_date", "breakout_close", "gap_bottom", "gap_top", "gap_pct", "gap_status"):
            result[field] = source.get(field)
        if scanner_id in ("bear_flag", "bear_flag_backtest") and history is not None:
            flag = history.loc[source.get("flag_start"):source.get("flag_end")]
            result["flag_high"] = float(flag.High.max()) if not flag.empty else None
            result["flag_low"] = float(flag.Low.min()) if not flag.empty else None
            result["breakout_date"] = candidate.get("signal_date")
        rows.append(result)
    return pd.DataFrame(rows)


def current_backtest_candidates(snapshot, now=None):
    """Only today's saved live scanner breakouts. Never accepts backtest trades.

    Fail closed on weekday holidays/uncertain freshness: no calendar or market
    query on this path. A holiday-old result remains visible on its scanner page.
    """
    empty = pd.DataFrame()
    if not snapshot or "patterns" not in snapshot or "details" not in snapshot:
        return empty, {}
    now = pd.Timestamp.now(tz="Asia/Taipei") if now is None else pd.Timestamp(now)
    now = now.tz_localize("Asia/Taipei") if now.tzinfo is None else now.tz_convert("Asia/Taipei")
    try:
        scanned = pd.Timestamp(snapshot["scan_time"])
        scanned = scanned.tz_localize("UTC") if scanned.tzinfo is None else scanned
        if scanned.tz_convert("Asia/Taipei").date() != now.date():
            return empty, {}
        expected = now.normalize().tz_localize(None)
        if now.hour < 14:
            expected -= pd.Timedelta(days=1)
        while expected.weekday() >= 5:
            expected -= pd.Timedelta(days=1)
        from src.bull_flag import filter_candidates
        cfg = snapshot["config"]
        candidates = filter_candidates(snapshot["patterns"], min_score=cfg.min_bull_flag_score,
                                       min_return=cfg.min_flagpole_return,
                                       flag_days=(cfg.min_flag_days, cfg.max_flag_days),
                                       max_retracement=cfg.max_retracement, status="BREAKOUT")
        if candidates.empty:
            return empty, {}
        candidates = candidates[pd.to_datetime(candidates.price_date).dt.normalize() == expected].copy()
        candidates = candidates[candidates.ticker.map(lambda t: t in snapshot["details"] and
                                pd.Timestamp(snapshot["details"][t].index[-1]).tz_localize(None).normalize() == expected)]
        return candidates, snapshot["details"]
    except (KeyError, ValueError, TypeError, AttributeError, IndexError):
        return empty, {}
