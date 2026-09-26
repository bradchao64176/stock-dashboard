"""Independent gap strategy using the existing causal Bull Flag signal generator.

All percentages are fractions. Market sessions are the union of observed positive-
volume dates, or an explicitly supplied reference calendar. Event discovery is
causal; subsequent gap preservation and current score are as-of observations.
"""
from dataclasses import replace
from datetime import datetime, timezone
import logging

import numpy as np
import pandas as pd

from backtesting.config import BacktestConfig
from backtesting.signals import prepare_history, generate_signals
from src.bull_flag_gap_config import GapConfig

LOGGER = logging.getLogger(__name__)
STATUSES = ("UNTOUCHED", "PARTIALLY_FILLED", "FILLED")
EVENT_COLUMNS = ["event_id", "rank", "stock_code", "stock_name", "market", "ticker", "current_close",
                 "MA20", "MA60", "bull_flag_score", "gap_breakout_score", "breakout_date", "gap_date",
                 "trading_days_since_breakout", "trading_days_since_gap", "breakout_price",
                 "breakout_volume_ratio", "previous_high", "gap_bottom", "gap_top", "gap_size", "gap_pct",
                 "gap_status", "gap_fill_pct", "remaining_gap_pct", "remaining_gap_size",
                 "lowest_price_after_gap", "distance_from_gap_pct", "gap_fill_date", "days_until_gap_fill",
                 "fill_data_complete", "gap_definition", "price_date"]


def normalize_dates(frame):
    frame = frame.copy()
    if "Date" in frame:
        frame["Date"] = pd.to_datetime(frame.Date, errors="coerce")
        frame = frame.set_index("Date")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.isna().any():
        raise ValueError("Invalid daily index")
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    frame.index = frame.index.normalize()
    if frame.index.duplicated().any():
        raise ValueError("Duplicate trading dates")
    return frame.sort_index()


def observed_sessions(histories):
    dates = set()
    for frame in histories.values():
        try:
            data = normalize_dates(frame)
            traded = pd.to_numeric(data.Volume, errors="coerce") > 0
            dates.update(data.index[traded])
        except (ValueError, AttributeError, KeyError):
            continue
    return pd.DatetimeIndex(sorted(dates))


def gap_zone(current, previous, definition="FULL_GAP", minimum=.01):
    bottom = float(previous.High)
    top = float(current.Low if definition == "FULL_GAP" else current.Open)
    if not np.isfinite([bottom, top]).all() or bottom <= 0 or top <= bottom:
        return None
    pct = (top - bottom) / bottom
    if pct + 1e-12 < minimum:
        return None
    return dict(previous_high=bottom, gap_bottom=bottom, gap_top=top,
                gap_size=top - bottom, gap_pct=pct, gap_definition=definition)


def fill_state(data, gap_pos, zone, end_pos=None):
    end_pos = len(data) - 1 if end_pos is None else end_pos
    after = data.iloc[gap_pos + 1:end_pos + 1]
    # An opening gap exists at the opening auction; its own candle can refill it.
    check_start = gap_pos if zone["gap_definition"] == "OPEN_GAP" else gap_pos + 1
    checked = data.iloc[check_start:end_pos + 1]
    known = checked[checked.valid_bar.astype(bool)]
    low = float(known.Low.min()) if not known.empty else np.nan
    later_valid = after[after.valid_bar.astype(bool)]
    later_low = float(later_valid.Low.min()) if not later_valid.empty else np.nan
    bottom, top, size = zone["gap_bottom"], zone["gap_top"], zone["gap_size"]
    filled = known[known.Low <= bottom]
    fill_date = filled.index[0] if not filled.empty else pd.NaT
    status = "FILLED" if not filled.empty else ("PARTIALLY_FILLED" if pd.notna(low) and low <= top else "UNTOUCHED")
    fraction = float(np.clip((top - low) / size, 0, 1)) if pd.notna(low) else 0.0
    return dict(gap_status=status, gap_fill_pct=fraction, remaining_gap_pct=1 - fraction,
                remaining_gap_size=size * (1 - fraction), remaining_gap_price_pct=size * (1 - fraction) / bottom,
                lowest_price_after_gap=later_low, lowest_price_since_gap=low,
                gap_fill_date=fill_date,
                days_until_gap_fill=int(data.index.get_loc(fill_date)) - gap_pos if pd.notna(fill_date) else None,
                fill_data_complete=bool(checked.valid_bar.all()))


def gap_component_scores(event, config):
    clip = lambda x: float(np.clip(x, 0, 1)) if np.isfinite(x) else 0.0
    w = config.weights
    trend = (clip((event["MA20"] / event["MA60"] - 1) / config.full_trend_spread)
             if event["current_close"] > event["MA20"] > event["MA60"] and event["current_MA20_slope"] > 0 else 0)
    return dict(bull_flag=w.bull_flag * clip(event["bull_flag_score"] / 100),
                breakout=w.breakout * clip(event["breakout_strength_pct"] / config.full_breakout_strength),
                gap_size=w.gap_size * clip(event["gap_pct"] / config.full_gap_size),
                volume=w.volume * clip(event["breakout_volume_ratio"] / config.full_volume_ratio),
                preservation=w.preservation * (1 - event["gap_fill_pct"]),
                current_trend=w.current_trend * trend)


def corporate_action_mask(data, config):
    """Conservative event exclusion, not reconstruction of corporate actions."""
    factor = data["Adj Close"] / data.Close
    changed = factor.pct_change(fill_method=None).abs() > config.adjustment_change_tolerance
    suspicious = data.Close.pct_change(fill_method=None).abs() > config.max_unexplained_daily_change
    for column in ("Stock Splits", "Dividends", "Capital Gains"):
        if column in data:
            changed |= pd.to_numeric(data[column], errors="coerce").fillna(0) != 0
    return changed | suspicious


def find_gap_events(data, stock, config=GapConfig()):
    cutoff_pos = max(0, len(data) - config.gap_lookback_days)
    # Search additional preceding bars only to link a gap with a near breakout.
    search_pos = max(0, cutoff_pos - config.gap_breakout_window)
    detector = replace(config.detector, breakout_volume_multiplier=config.min_breakout_volume_ratio)
    causal_config = BacktestConfig(detector=detector, require_breakout_volume=False)
    signals = generate_signals(data, stock, causal_config, signal_start=data.index[search_pos])
    events, issues = [], []
    action = corporate_action_mask(data, config)
    for signal in signals:
        bp = int(signal["signal_index"])
        if len(data) - 1 - bp >= config.gap_lookback_days:
            continue
        if config.require_gap_volume_confirmation and signal["breakout_volume_ratio"] < config.min_breakout_volume_ratio:
            continue
        for gp in range(max(1, bp - config.gap_breakout_window), min(len(data), bp + config.gap_breakout_window + 1)):
            if gp < cutoff_pos or not data.iloc[gp - 1:gp + 1].valid_bar.all():
                continue
            zone = gap_zone(data.iloc[gp], data.iloc[gp - 1], config.gap_definition, config.min_gap_pct)
            if zone is None:
                continue
            recognition = max(bp, gp)
            pole_pos = data.index.get_loc(signal["flagpole_start"])
            # Do not certify a pattern crossing a corporate action or an untracked
            # change of price basis, nor its subsequent preservation across one.
            if action.iloc[pole_pos:recognition + 1].any():
                issues.append(dict(ticker=stock["ticker"], date=str(data.index[gp].date()),
                                   reason="Corporate action / price-basis discontinuity in setup"))
                continue
            breakout = data.iloc[bp]
            current = data.iloc[-1]
            state = fill_state(data, gp, zone)
            at_signal = fill_state(data, gp, zone, recognition)
            after_action = bool(action.iloc[recognition + 1:].any())
            state["fill_data_complete"] = state["fill_data_complete"] and not after_action
            event = dict(signal)
            event.update(zone)
            event.update(state)
            event.update(
                event_id=f'{stock["ticker"]}:{data.index[bp].date()}:{data.index[gp].date()}:{config.gap_definition}',
                strategy="BULL_FLAG_GAP", breakout_date=data.index[bp], gap_date=data.index[gp],
                breakout_open=float(breakout.Open), breakout_high=float(breakout.High),
                breakout_low=float(breakout.Low), breakout_close=float(breakout.Close),
                breakout_volume=float(breakout.Volume), breakout_price=float(breakout.Close),
                breakout_MA20=float(breakout.MA20), breakout_MA60=float(breakout.MA60),
                breakout_MA20_slope=float(breakout.MA20_slope), breakout_signal_index=bp,
                breakout_strength_pct=float(breakout.Close / signal["upper_flag_trendline"] - 1),
                gap_index=gp, gap_breakout_offset=gp - bp,
                trading_days_since_breakout=len(data) - 1 - bp, trading_days_since_gap=len(data) - 1 - gp,
                current_close=float(current.Close), MA20=float(current.MA20), MA60=float(current.MA60),
                current_MA20_slope=float(current.MA20_slope), price_date=data.index[-1],
                distance_from_gap_pct=float(current.Close / zone["gap_top"] - 1),
                signal_date=data.index[recognition], signal_index=recognition,
                signal_close=float(data.Close.iloc[recognition]), signal_atr=float(data.ATR.iloc[recognition]),
                gap_status_at_signal=at_signal["gap_status"], gap_fill_pct_at_signal=at_signal["gap_fill_pct"],
                signal_data_complete=at_signal["fill_data_complete"],
                corporate_action_after_event=after_action,
            )
            scores = gap_component_scores(event, config)
            event.update({f"gap_score_{name}": round(value, 2) for name, value in scores.items()})
            event["gap_breakout_score"] = round(sum(scores.values()), 2)
            # Snapshot at recognition avoids feeding current preservation into a
            # future backtest's historical entry filters.
            signal_event = dict(event, **at_signal)
            signal_event.update(current_close=float(data.Close.iloc[recognition]),
                                MA20=float(data.MA20.iloc[recognition]), MA60=float(data.MA60.iloc[recognition]),
                                current_MA20_slope=float(data.MA20_slope.iloc[recognition]))
            event["gap_score_at_signal"] = round(sum(gap_component_scores(signal_event, config).values()), 2)
            events.append(event)
    return events, issues


def filter_gap_events(events, market="All", statuses=("UNTOUCHED", "PARTIALLY_FILLED"),
                      only_untouched=False, min_bull_flag_score=60, min_gap_score=0,
                      min_gap_pct=.01, require_volume=True, min_volume_ratio=1.2, latest_only=True):
    if events.empty:
        return events.copy()
    chosen = events[events.fill_data_complete & events.gap_status.isin(statuses)
                    & (events.bull_flag_score >= min_bull_flag_score)
                    & (events.gap_breakout_score >= min_gap_score) & (events.gap_pct + 1e-12 >= min_gap_pct)]
    if market != "All":
        chosen = chosen[chosen.market == market]
    if only_untouched:
        chosen = chosen[chosen.gap_status == "UNTOUCHED"]
    if require_volume:
        chosen = chosen[chosen.breakout_volume_ratio >= min_volume_ratio]
    # Filter BEFORE selecting the newest gap: a newer filled gap must not hide an
    # older qualifying unfilled one. Keep all events in the source snapshot.
    chosen = chosen.sort_values(["gap_date", "breakout_date", "gap_breakout_score"], ascending=False)
    if latest_only:
        chosen = chosen.drop_duplicates("ticker")
    chosen = chosen.sort_values(["gap_breakout_score", "ticker"], ascending=[False, True]).reset_index(drop=True).copy()
    chosen["rank"] = np.arange(1, len(chosen) + 1)
    return chosen


def scan_gap_universe(universe, histories, config=GapConfig(), market_sessions=None, progress=None):
    sessions = observed_sessions(histories) if market_sessions is None else pd.DatetimeIndex(market_sessions).normalize().unique().sort_values()
    records, issues, details = [], [], {}
    analyzed = 0
    stocks = universe.drop_duplicates("ticker").to_dict("records")
    for count, stock in enumerate(stocks, 1):
        ticker = stock["ticker"]
        try:
            if sessions.empty:
                raise ValueError("No observed market sessions")
            if ticker not in histories:
                raise ValueError("No downloaded history")
            raw = normalize_dates(histories[ticker])
            if raw.empty:
                raise ValueError("Empty history")
            aligned = raw.reindex(sessions[sessions >= raw.index[0]])
            data = prepare_history(aligned, BacktestConfig(detector=config.detector))
            if not bool(data.valid_bar.iloc[-1]):
                raise ValueError("Latest market session missing/invalid; cannot certify current unfilled gap")
            found, rejected = find_gap_events(data, stock, config)
            records.extend(found)
            issues.extend(rejected)
            incomplete = sum(not event["fill_data_complete"] for event in found)
            if incomplete:
                issues.append(dict(ticker=ticker, reason=f"{incomplete} events cannot certify gap fill history"))
            if found:
                details[ticker] = data
            analyzed += 1
        except Exception as error:
            issues.append(dict(ticker=ticker, reason=str(error)))
        if progress:
            progress(count, len(stocks))
    for issue in issues:
        LOGGER.warning("Gap %s: %s", issue["ticker"], issue["reason"])
    events = pd.DataFrame(records) if records else pd.DataFrame(columns=EVENT_COLUMNS)
    selected = filter_gap_events(events, only_untouched=config.only_untouched_gaps,
                                 min_bull_flag_score=config.detector.min_bull_flag_score,
                                 min_gap_score=config.min_gap_breakout_score, min_gap_pct=config.min_gap_pct,
                                 require_volume=config.require_gap_volume_confirmation,
                                 min_volume_ratio=config.min_breakout_volume_ratio)
    return dict(events=events, candidates=selected, details=details, issues=issues, config=config,
                market_date=sessions[-1] if len(sessions) else pd.NaT,
                scan_time=datetime.now(timezone.utc).isoformat(),
                stats=dict(total=len(stocks), downloaded=sum(s["ticker"] in histories for s in stocks),
                           analyzed=analyzed, skipped=len(stocks) - analyzed, events=len(events), candidates=len(selected)))


def to_backtest_signal(event):
    """Adapter to existing execute_backtest; never filter using current fill status.

    Supply ALL historical events (including those later filled), not today's
    survivors. Entry is after max(breakout, gap) recognition, using known-at-T ATR.
    """
    if not event["signal_data_complete"] or event["gap_status_at_signal"] == "FILLED":
        return None
    fields = ["stock_code", "stock_name", "market", "ticker", "signal_date", "signal_index", "signal_close",
              "signal_atr", "flag_swing_low", "flagpole_return_pct", "pullback_pct", "retracement", "volume_ratio",
              "bull_flag_score", "breakout_volume_ratio", "flagpole_start", "flag_start", "flag_end", "flag_days",
              "high_slope", "low_slope", "high_intercept", "low_intercept", "upper_flag_trendline", "gap_date",
              "breakout_date", "gap_bottom", "gap_top", "gap_size", "gap_pct", "gap_definition", "gap_score_at_signal"]
    result = {name: event[name] for name in fields}
    result.update(signal_id=event["event_id"], MA20=event["breakout_MA20"], MA60=event["breakout_MA60"])
    return result
