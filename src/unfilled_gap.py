"""Trend-filtered unfilled gaps. Reuses gap/fill logic and the existing indicators."""
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from backtesting.config import BacktestConfig
from backtesting.signals import prepare_history
from backtesting.engine import execute_backtest
from src.bull_flag_config import BullFlagConfig
from src.bull_flag_gap import (normalize_dates, observed_sessions, gap_zone, fill_state, corporate_action_mask)
from src.unfilled_gap_config import UnfilledGapConfig, TrendConfig

EMPTY_COLUMNS = ["event_id", "rank", "stock_code", "stock_name", "ticker", "market", "gap_date",
                 "gap_status", "gap_pct", "gap_fill_pct", "unfilled_gap_score", "fill_data_complete"]


def prepare_trend_history(history, config=UnfilledGapConfig()):
    minimum = max(65, 60 + config.trend.ma_slope_lookback, config.return_lookback_days + 1)
    data = prepare_history(history, BacktestConfig(detector=BullFlagConfig(min_history_days=minimum)))
    if not all(column in data for column in ("MA5", "MA10", "MA20", "MA60")):
        raise ValueError("No valid price history for moving averages")
    lookback = config.trend.ma_slope_lookback
    for period in (20, 60):
        slope = data[f"MA{period}"] / data[f"MA{period}"].shift(lookback) - 1
        data[f"ma{period}_slope_pct"] = slope.where(data.valid_streak >= period + lookback)
    data["recent_return_pct"] = (data.Close / data.Close.shift(config.return_lookback_days) - 1).where(
        data.valid_streak > config.return_lookback_days)
    data["ma20_ma60_distance_pct"] = data.MA20 / data.MA60 - 1
    cross = (data.MA20 > data.MA60) & (data.MA20.shift(1) <= data.MA60.shift(1))
    segment = (~data.valid_bar).cumsum()
    cross_dates = pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns]")
    cross_dates.loc[cross] = data.index[cross]
    data["ma20_ma60_cross_date"] = cross_dates.groupby(segment).ffill()
    cross_positions = pd.Series(np.where(cross, np.arange(len(data)), np.nan), index=data.index).groupby(segment).ffill()
    data["trading_days_since_golden_cross"] = np.arange(len(data)) - cross_positions
    return data


def trend_values(row, prefix):
    result = {f"{prefix}_close": float(row.Close)}
    for period in (5, 10, 20, 60):
        result[f"{prefix}_ma{period}"] = float(row[f"MA{period}"])
    for name in ("ma20_slope_pct", "ma60_slope_pct", "ma20_ma60_distance_pct", "recent_return_pct",
                 "ma20_ma60_cross_date", "trading_days_since_golden_cross"):
        result[f"{prefix}_{name}"] = row[name]
    result.update({f"{prefix}_close_above_ma20": bool(row.Close > row.MA20),
                   f"{prefix}_ma20_above_ma60": bool(row.MA20 > row.MA60),
                   f"{prefix}_ma20_rising": bool(row.ma20_slope_pct > 0),
                   f"{prefix}_ma60_rising": bool(row.ma60_slope_pct > 0),
                   f"{prefix}_full_ma_alignment": bool(row.Close > row.MA5 > row.MA10 > row.MA20 > row.MA60)})
    return result


def trend_passes(event, prefix, config):
    rules = ((config.require_close_above_ma20, "close_above_ma20"),
             (config.require_ma20_above_ma60, "ma20_above_ma60"),
             (config.require_ma20_rising, "ma20_rising"),
             (config.require_ma60_rising, "ma60_rising"),
             (config.require_full_ma_alignment, "full_ma_alignment"))
    if any(required and not bool(event[f"{prefix}_{field}"]) for required, field in rules):
        return False
    if config.enable_distance_filter:
        distance = event[f"{prefix}_ma20_ma60_distance_pct"]
        if not np.isfinite(distance) or distance < config.min_ma20_ma60_distance_pct:
            return False
        if config.max_ma20_ma60_distance_pct is not None and distance > config.max_ma20_ma60_distance_pct:
            return False
    return True


def trend_mode_passes(event, config):
    mode = config.trend_evaluation
    return ((mode == "CURRENT" or trend_passes(event, "gap_day", config))
            and (mode == "GAP_DAY" or trend_passes(event, "current", config)))


def score_event(event, config):
    clip = lambda value: float(np.clip(value, 0, 1)) if np.isfinite(value) else 0.0
    def trend_quality(prefix):
        return (float(event[f"{prefix}_close_above_ma20"]) + float(event[f"{prefix}_ma20_above_ma60"])
                + clip(event[f"{prefix}_ma20_slope_pct"] / config.full_ma20_slope)
                + clip(event[f"{prefix}_ma60_slope_pct"] / config.full_ma60_slope)
                + clip(event[f"{prefix}_ma20_ma60_distance_pct"] / config.full_ma_distance)) / 5
    mode = config.trend.trend_evaluation
    prefixes = ["gap_day", "current"] if mode == "GAP_DAY_AND_CURRENT" else ["gap_day" if mode == "GAP_DAY" else "current"]
    w = config.weights
    return dict(trend_quality=w.trend_quality * np.mean([trend_quality(p) for p in prefixes]),
                recent_return=w.recent_return * clip(event["recent_return_pct"] / config.full_return),
                gap_size=w.gap_size * clip(event["gap_pct"] / config.full_gap_size),
                preservation=w.preservation * (1 - event["gap_fill_pct"]),
                post_gap_strength=w.post_gap_strength * clip(event["post_gap_return_pct"] / config.full_post_gap_strength),
                gap_volume=w.gap_volume * clip(event["gap_volume_ratio"] / config.full_volume_ratio))


def find_unfilled_events(data, stock, config=UnfilledGapConfig()):
    events = []
    actions = corporate_action_mask(data, config)
    for pos in range(max(1, len(data) - config.gap_lookback_days), len(data)):
        if not data.iloc[pos - 1:pos + 1].valid_bar.all():
            continue
        row = data.iloc[pos]
        zone = gap_zone(row, data.iloc[pos - 1], config.gap_definition, 0)
        if zone is None or actions.iloc[pos]:
            continue
        state = fill_state(data, pos, zone)
        initial = fill_state(data, pos, zone, pos)
        state["fill_data_complete"] = state["fill_data_complete"] and not bool(actions.iloc[pos + 1:].any())
        event = dict(stock, **zone, **state)
        event.update(trend_values(row, "gap_day"))
        event.update(trend_values(data.iloc[-1], "current"))
        baseline = float(data.Volume.iloc[max(0, pos - 20):pos].mean()) if pos >= 20 else np.nan
        event.update(event_id=f'{stock["ticker"]}:{data.index[pos].date()}:{config.gap_definition}',
                     strategy="UNFILLED_BULLISH_GAP", gap_date=data.index[pos], gap_index=pos,
                     signal_date=data.index[pos], signal_index=pos, signal_close=float(row.Close),
                     signal_atr=float(row.ATR), flag_swing_low=float(zone["gap_bottom"]),
                     gap_day_volume=float(row.Volume), gap_volume_baseline=baseline,
                     gap_volume_ratio=float(row.Volume / baseline) if baseline > 0 else np.nan,
                     gap_status_at_signal=initial["gap_status"], gap_fill_pct_at_signal=initial["gap_fill_pct"],
                     signal_data_complete=bool(row.valid_bar), price_date=data.index[-1],
                     trading_days_since_gap=len(data) - 1 - pos,
                     recent_return_pct=event["current_recent_return_pct"],
                     post_gap_return_pct=float(data.Close.iloc[-1] / row.Close - 1),
                     ma20_ma60_distance_pct=event["current_ma20_ma60_distance_pct"],
                     ma20_ma60_cross_date=event["current_ma20_ma60_cross_date"],
                     trading_days_since_golden_cross=event["current_trading_days_since_golden_cross"],
                     gap_day_trend_pass=trend_passes(event, "gap_day", config.trend),
                     current_trend_pass=trend_passes(event, "current", config.trend),
                     return_lookback_days=config.return_lookback_days, ma_slope_lookback=config.trend.ma_slope_lookback)
        scores = score_event(event, config)
        event.update({f"score_{name}": round(float(points), 2) for name, points in scores.items()})
        event["unfilled_gap_score"] = round(sum(scores.values()), 2)
        # At recognition 'current' is gap day. This snapshot contains no later fill
        # path, current return, golden cross or trend information.
        at_signal = dict(event)
        at_signal.update(trend_values(row, "current"))
        at_signal.update(initial)
        at_signal.update(recent_return_pct=event["gap_day_recent_return_pct"], post_gap_return_pct=0)
        event["score_at_signal"] = round(sum(score_event(at_signal, config).values()), 2)
        events.append(event)
    return events


def filter_unfilled_events(events, config=UnfilledGapConfig(), market="All",
                           statuses=("UNTOUCHED", "PARTIALLY_FILLED"), latest_only=True):
    if events.empty:
        return events.copy()
    mask = (events.fill_data_complete & events.gap_status.isin(statuses)
            & (events.gap_pct + 1e-12 >= config.min_gap_pct)
            & (events.recent_return_pct + 1e-12 >= config.min_return_pct)
            & (events.unfilled_gap_score >= config.min_score))
    mask &= events.apply(lambda row: trend_mode_passes(row, config.trend), axis=1)
    if config.only_untouched_gaps:
        mask &= events.gap_status == "UNTOUCHED"
    if config.require_volume_confirmation:
        mask &= events.gap_volume_ratio >= config.min_volume_ratio
    if market != "All":
        mask &= events.market == market
    result = events[mask].sort_values(["gap_date", "unfilled_gap_score"], ascending=False)
    if latest_only:
        result = result.drop_duplicates("ticker")
    result = result.sort_values(["unfilled_gap_score", "ticker"], ascending=[False, True]).reset_index(drop=True).copy()
    result["rank"] = np.arange(1, len(result) + 1)
    return result


def scan_unfilled_universe(universe, histories, config=UnfilledGapConfig(), market_sessions=None, progress=None):
    sessions = observed_sessions(histories) if market_sessions is None else pd.DatetimeIndex(market_sessions).normalize().unique().sort_values()
    records, issues, details = [], [], {}
    analyzed = 0
    stocks = universe.drop_duplicates("ticker").to_dict("records")
    for count, stock in enumerate(stocks, 1):
        ticker = stock["ticker"]
        try:
            if sessions.empty or ticker not in histories:
                raise ValueError("No market sessions or downloaded history")
            raw = normalize_dates(histories[ticker])
            if raw.empty:
                raise ValueError("Empty history")
            data = prepare_trend_history(raw.reindex(sessions[sessions >= raw.index[0]]), config)
            if not data.valid_bar.iloc[-1]:
                raise ValueError("Latest market session missing/invalid")
            found = find_unfilled_events(data, stock, config)
            records.extend(found)
            if found:
                details[ticker] = data
            analyzed += 1
        except Exception as error:
            issues.append(dict(ticker=ticker, reason=str(error)))
        if progress:
            progress(count, len(stocks))
    events = pd.DataFrame(records) if records else pd.DataFrame(columns=EMPTY_COLUMNS)
    candidates = filter_unfilled_events(events, config)
    return dict(events=events, candidates=candidates, details=details, issues=issues, config=config,
                market_date=sessions[-1] if len(sessions) else pd.NaT,
                scan_time=datetime.now(timezone.utc).isoformat(),
                stats=dict(total=len(stocks), downloaded=sum(s["ticker"] in histories for s in stocks),
                           analyzed=analyzed, skipped=len(stocks) - analyzed, events=len(events), candidates=len(candidates)))


def to_unfilled_backtest_signal(event, config=UnfilledGapConfig()):
    """Entry filters at gap close only. Never condition on today's surviving gaps."""
    if (not event["signal_data_complete"] or event["gap_status_at_signal"] == "FILLED"
            or event["gap_pct"] < config.min_gap_pct
            or not (event["gap_day_recent_return_pct"] >= config.min_return_pct)
            or not trend_passes(event, "gap_day", config.trend)):
        return None
    if config.only_untouched_gaps and event["gap_status_at_signal"] != "UNTOUCHED":
        return None
    if config.require_volume_confirmation and not event["gap_volume_ratio"] >= config.min_volume_ratio:
        return None
    if event["score_at_signal"] < config.min_score:
        return None
    fields = ["stock_code", "stock_name", "ticker", "market", "signal_date", "signal_index", "signal_close",
              "signal_atr", "flag_swing_low", "gap_date", "gap_index", "gap_top", "gap_bottom", "gap_pct",
              "gap_volume_ratio", "score_at_signal", "return_lookback_days", "ma_slope_lookback"]
    signal = {field: event[field] for field in fields}
    signal.update({key: value for key, value in event.items() if key.startswith("gap_day_")})
    signal.update(signal_id=event["event_id"], MA20=event["gap_day_ma20"], MA60=event["gap_day_ma60"])
    return signal


def compare_trend_variants(events, histories, base=UnfilledGapConfig(), execution=BacktestConfig()):
    """Shared non-MA rules, five signal-time trend variants, existing RR execution.

    Caller must supply an uncensored historical EVENT set, not today's candidates.
    Forward close returns are research outcomes, never signal inputs.
    """
    relaxed = replace(base.trend, require_close_above_ma20=False, require_ma20_above_ma60=False,
                      require_ma20_rising=False, require_ma60_rising=False, require_full_ma_alignment=False,
                      enable_distance_filter=False, trend_evaluation="GAP_DAY")
    variants = {"GAP_ONLY": relaxed,
                "MA20_ABOVE_MA60": replace(relaxed, require_ma20_above_ma60=True),
                "CLOSE_MA20_MA60": replace(relaxed, require_ma20_above_ma60=True, require_close_above_ma20=True),
                "RISING_MA20": replace(relaxed, require_ma20_above_ma60=True, require_close_above_ma20=True, require_ma20_rising=True),
                "FULL_ALIGNMENT": replace(relaxed, require_full_ma_alignment=True)}
    results = {}
    for name, trend in variants.items():
        cfg = replace(base, trend=trend)
        signals = [to_unfilled_backtest_signal(row, cfg) for row in events.to_dict("records")]
        signals = pd.DataFrame([s for s in signals if s is not None])
        forwards = []
        for signal in signals.to_dict("records"):
            data = histories[signal["ticker"]]
            entry = int(signal["signal_index"]) + 1
            row = dict(signal_id=signal["signal_id"])
            for days in (5, 10, 20, 30):
                end = entry + days - 1
                value = np.nan
                if end < len(data) and data.iloc[entry:end + 1].valid_bar.all():
                    value = float(data.Close.iloc[end] / data.Open.iloc[entry] - 1)
                row[f"return_{days}d"] = value
            forwards.append(row)
        result = execute_backtest(dict(signals=signals, histories=histories, issues=[], stats={}), execution)
        result["forward_returns"] = pd.DataFrame(forwards)
        results[name] = result
    return results
