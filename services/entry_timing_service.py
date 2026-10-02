"""Pure analysis of already-selected Strong candidates. No IO or notifications.

Pass scanner details (causal indicators) or raw OHLCV and the scanner's
ImpulseConfig. For historical evaluation, candidate selection must itself be
point-in-time; this module never selects candidates or fixes survivorship bias.
"""
import math

import pandas as pd

from services.entry_timing_config import EntryTimingConfig
from src.impulse_macd import ImpulseConfig, calculate_impulse


STATUS_LABELS = {
    "PULLBACK_ZONE": "🟢 PULLBACK ZONE", "BREAKOUT_ZONE": "🔵 BREAKOUT ZONE",
    "CROSS_ENTRY": "🟡 CROSS ENTRY", "WATCH": "🟡 WATCH", "EXTENDED": "🟠 EXTENDED",
    "HIGHLY_EXTENDED": "🔴 HIGHLY EXTENDED", "MISSED": "MISSED",
    "TREND_INVALIDATED": "🔴 TREND INVALIDATED", "UNKNOWN": "UNKNOWN",
}


def calculate_pullback_zone(ma20, config=EntryTimingConfig()):
    return ma20 * (1 + config.pullback_low_pct), ma20 * (1 + config.pullback_high_pct)


def calculate_breakout_zone(resistance, config=EntryTimingConfig()):
    return resistance, resistance * (1 + config.breakout_buffer_pct)


def calculate_cross_entry_zone(high, config=EntryTimingConfig()):
    return high, high * (1 + config.cross_entry_buffer_pct)


def calculate_histogram_direction(current, previous):
    if not all(math.isfinite(v) for v in (current, previous)):
        return None
    return "WEAK" if current <= 0 else ("EXPANDING" if current > previous else "COOLING")


def calculate_atr(data, period=14):
    # Reuse the existing Impulse ATR14 or the existing configurable backtest ATR.
    if period == 14:
        return (data if "ATR" in data else calculate_impulse(data))["ATR"].copy()
    from dataclasses import replace
    from backtesting.config import BacktestConfig
    from backtesting.signals import prepare_history
    cfg = BacktestConfig(atr_period=period)
    cfg = replace(cfg, detector=replace(cfg.detector, min_history_days=60))
    raw = data.copy(deep=True)
    if "Adj Close" not in raw:
        raw["Adj Close"] = raw.Close
    return prepare_history(raw, cfg)["ATR"].copy()


def find_recent_swing_low(data, lookback=10):
    return float(data.Low.shift(1).rolling(lookback).min().iloc[-1])


def calculate_reference_stop(entry, ma20, atr, swing_low, config=EntryTimingConfig()):
    ma_stop = ma20 - config.atr_stop_multiplier * atr
    choices = [("SWING_LOW", swing_low), ("MA20_ATR", ma_stop)] if config.stop_mode == "STRUCTURAL" else [("MA20_ATR", ma_stop)]
    for source, stop in choices:
        if math.isfinite(stop) and 0 < stop < entry:
            return ma_stop, stop, source
    return ma_stop, None, None


def calculate_risk_targets(entry, stop):
    result = dict(risk_status="INVALID_RISK_STRUCTURE", risk_per_share=None, risk_pct=None,
                  target_2r=None, target_3r=None)
    if stop is None or not all(math.isfinite(v) for v in (entry, stop)) or not 0 < stop < entry:
        return result
    risk = entry - stop
    return dict(risk_status="VALID", risk_per_share=risk, risk_pct=100 * risk / entry,
                target_2r=entry + 2 * risk, target_3r=entry + 3 * risk)


def classify_entry_status(trend_valid, pullback, breakout, cross, distance, config=EntryTimingConfig()):
    if not trend_valid:
        return "TREND_INVALIDATED"
    for qualifies, status in ((pullback, "PULLBACK_ZONE"), (breakout, "BREAKOUT_ZONE"), (cross, "CROSS_ENTRY")):
        if qualifies:
            return status
    # Arithmetic such as (112 / 100 - 1) * 100 can exceed 12 by machine epsilon.
    if distance <= config.watch_max_distance_pct * 100 or math.isclose(distance, config.watch_max_distance_pct * 100, rel_tol=1e-12):
        return "WATCH"
    return "EXTENDED" if distance <= config.extended_max_distance_pct * 100 or math.isclose(distance, config.extended_max_distance_pct * 100, rel_tol=1e-12) else "HIGHLY_EXTENDED"


def _day(value):
    day = pd.Timestamp(value)
    if day.tzinfo is not None:
        day = day.tz_convert("Asia/Taipei").tz_localize(None)
    return day.normalize()


def calculate_entry_analysis(candidate, history, config=EntryTimingConfig(), asof=None,
                             impulse_config=ImpulseConfig()):
    """Return one independent result, never mutating candidate/history.

    asof is the last available daily candle date. Supplied indicator columns
    must come from the project's causal indicator engine, never centered windows.
    """
    fields = ("analysis_date current_price ma20 ma60 ma20_rising distance_ma20_pct impulse_macd impulse_signal "
              "histogram previous_histogram histogram_change histogram_direction current_volume_ratio cross_day_volume_ratio "
              "volume_contraction recent_20d_high cross_date cross_day_high cross_day_low cross_day_close cross_age_days "
              "pullback_entry_low pullback_entry_high breakout_entry_low breakout_entry_high cross_entry_low cross_entry_high "
              "primary_entry_type primary_entry_low primary_entry_high entry_zone_low entry_zone_high entry_reference_price "
              "atr14 atr atr_period recent_swing_low stop_ma20 reference_stop stop_source").split()
    result = dict.fromkeys(fields)
    result.update({k: candidate.get(k) for k in ("ticker", "stock_code", "stock_name", "strong_golden_cross_score")})
    result.update(entry_status="UNKNOWN", reason=None, is_pullback_entry=False, is_breakout_entry=False,
                  is_cross_entry=False, cross_entry_missed=False, action="INSUFFICIENT_DATA")
    result.update(calculate_risk_targets(0, None))
    try:
        selected = candidate.get("strong_golden_cross", False)
        if pd.isna(selected) or selected != True:
            raise ValueError("Input must be an existing Strong Golden Cross candidate")
        if history is None or history.empty or not isinstance(history.index, pd.DatetimeIndex):
            raise ValueError("Missing daily history")
        data = history.copy(deep=True)
        data.index = pd.DatetimeIndex([_day(d) for d in data.index])
        if data.index.hasnans or data.index.has_duplicates:
            raise ValueError("Invalid daily dates")
        data = data.sort_index()
        if asof is not None:
            data = data.loc[:_day(asof)].copy()
        if data.empty:
            raise ValueError("No history at analysis date")
        indicators = ["MA20", "MA60", "ma20_slope_pct", "Impulse_MACD", "Impulse_Signal", "Impulse_Histogram", "volume_ratio_20", "ATR", "golden_cross"]
        if any(col not in data for col in indicators):
            data = calculate_impulse(data, impulse_config)
        required = ["Open", "High", "Low", "Close", "Volume"] + indicators[:-1]
        values = [float(data[col].iloc[-1]) for col in required]
        if len(data) < max(config.resistance_lookback, config.swing_lookback) + 1 or not all(math.isfinite(v) for v in values):
            raise ValueError("Missing current data or insufficient indicator/history warmup")
        row = data.iloc[-1]
        if min(row.Open, row.High, row.Low, row.Close, row.MA20, row.MA60) <= 0 or row.Volume < 0 or row.High < max(row.Open, row.Close, row.Low) or row.Low > min(row.Open, row.Close):
            raise ValueError("Invalid current OHLCV/averages")
        cross_date = _day(candidate.get("golden_cross_date", candidate.get("cross_date")))
        if cross_date not in data.index:
            raise ValueError("Cross date missing or after analysis date")
        cross = data.loc[cross_date]
        if pd.isna(cross.golden_cross) or not bool(cross.golden_cross):
            raise ValueError("Candidate date is not an actual golden cross")
        age = len(data) - 1 - data.index.get_loc(cross_date)
        resistance = float(data.High.shift(1).rolling(config.resistance_lookback).max().iloc[-1])
        swing = find_recent_swing_low(data, config.swing_lookback)
        atr = float(calculate_atr(data, config.atr_period).iloc[-1])
        prev = float(data.Impulse_Histogram.iloc[-2])
        if not all(math.isfinite(float(v)) for v in (resistance, swing, atr, prev, cross.High, cross.Low, cross.Close)) or atr < 0 or min(resistance, swing, cross.High, cross.Low, cross.Close) <= 0:
            raise ValueError("Missing reference bars")
        low, high = calculate_pullback_zone(row.MA20, config)
        blo, bhi = calculate_breakout_zone(resistance, config)
        clo, chi = calculate_cross_entry_zone(cross.High, config)
        direction = calculate_histogram_direction(row.Impulse_Histogram, prev)
        contraction = bool(row.volume_ratio_20 < cross.volume_ratio_20) if math.isfinite(cross.volume_ratio_20) else None
        trend = bool(row.Close >= row.MA20 and row.MA20 > row.MA60 and row.ma20_slope_pct > 0)
        momentum = bool(row.Impulse_MACD > row.Impulse_Signal and row.Impulse_Histogram > 0)
        pullback = trend and momentum and low <= row.Close <= high and (not config.require_volume_contraction or contraction is True)
        breakout = trend and momentum and blo <= row.Close <= bhi and row.volume_ratio_20 >= config.breakout_volume_ratio and (not config.require_expanding_breakout or direction == "EXPANDING")
        cross_entry = trend and momentum and clo <= row.Close <= chi and age <= config.max_cross_entry_age_days
        distance = (row.Close / row.MA20 - 1) * 100
        status = classify_entry_status(trend, pullback, breakout, cross_entry, distance, config)
        kind, elo, ehi = ("BREAKOUT", blo, bhi) if status == "BREAKOUT_ZONE" else (("CROSS", clo, chi) if status == "CROSS_ENTRY" else ("PULLBACK", low, high))
        entry = (elo + ehi) / 2
        ma_stop, stop, source = calculate_reference_stop(entry, row.MA20, atr, swing, config)
        result.update(analysis_date=str(data.index[-1].date()), current_price=float(row.Close), ma20=float(row.MA20), ma60=float(row.MA60),
                      ma20_rising=bool(row.ma20_slope_pct > 0), distance_ma20_pct=float(distance), impulse_macd=float(row.Impulse_MACD),
                      impulse_signal=float(row.Impulse_Signal), histogram=float(row.Impulse_Histogram), previous_histogram=prev,
                      histogram_change=float(row.Impulse_Histogram - prev), histogram_direction=direction,
                      current_volume_ratio=float(row.volume_ratio_20), cross_day_volume_ratio=float(cross.volume_ratio_20), volume_contraction=contraction,
                      recent_20d_high=resistance, cross_date=str(cross_date.date()), cross_day_high=float(cross.High), cross_day_low=float(cross.Low),
                      cross_day_close=float(cross.Close), cross_age_days=age, pullback_entry_low=float(low), pullback_entry_high=float(high),
                      breakout_entry_low=float(blo), breakout_entry_high=float(bhi), cross_entry_low=float(clo), cross_entry_high=float(chi),
                      entry_status=status, is_pullback_entry=bool(pullback), is_breakout_entry=bool(breakout), is_cross_entry=bool(cross_entry),
                      cross_entry_missed=bool(row.Close > chi), primary_entry_type=kind, primary_entry_low=float(elo), primary_entry_high=float(ehi),
                      entry_zone_low=float(elo), entry_zone_high=float(ehi), entry_reference_price=float(entry), atr14=float(row.ATR), atr=atr,
                      atr_period=config.atr_period, recent_swing_low=swing, stop_ma20=float(ma_stop), reference_stop=stop, stop_source=source,
                      action="REFERENCE_ZONE_ACTIVE" if status in ("PULLBACK_ZONE", "BREAKOUT_ZONE", "CROSS_ENTRY") else
                      ("TREND_INVALIDATED" if status == "TREND_INVALIDATED" else "WAIT_FOR_PULLBACK"))
        result.update(calculate_risk_targets(entry, stop))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        result["reason"] = str(error)
    return result


def analyze_candidates(candidates, histories, config=EntryTimingConfig(), asof=None, impulse_config=ImpulseConfig()):
    """Preserve candidate order and membership; UNKNOWN remains visible."""
    return pd.DataFrame([calculate_entry_analysis(row, histories.get(row["ticker"]), config, asof, impulse_config)
                         for row in candidates.to_dict("records")])
