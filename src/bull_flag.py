"""Deterministic bullish descending-channel scanner. No network/UI dependencies."""
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.bull_flag_config import BullFlagConfig

LOGGER = logging.getLogger(__name__)
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close"]
RESULT_COLUMNS = ["rank", "stock_code", "stock_name", "market", "ticker", "status", "close",
                  "MA20", "MA60", "flagpole_return_pct", "pullback_pct", "high_slope", "low_slope",
                  "volume_ratio", "breakout_volume_ratio", "bull_flag_score", "scan_time"]


def validate_history(history, min_days=120):
    if history is None or history.empty:
        raise ValueError("Empty history")
    data = history.copy()
    if "Date" in data.columns:
        data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
        data = data.set_index("Date")
    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("History requires a DatetimeIndex or Date column")
    if data.index.isna().any() or data.index.normalize().duplicated().any():
        raise ValueError("Missing or duplicated trading dates")
    if any(c not in data for c in PRICE_COLUMNS + ["Volume"]):
        raise ValueError("Missing OHLC, Adj Close or Volume column")
    data = data.sort_index()
    for column in PRICE_COLUMNS + ["Volume"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    values = data[PRICE_COLUMNS + ["Volume"]]
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("Missing or non-finite OHLCV values")
    if (data[PRICE_COLUMNS] <= 0).any().any() or (data.Volume < 0).any():
        raise ValueError("Nonpositive price or negative volume")
    if ((data.High < data[["Open", "Close", "Low"]].max(axis=1)).any()
            or (data.Low > data[["Open", "Close", "High"]].min(axis=1)).any()):
        raise ValueError("Invalid OHLC bounds")
    if len(data) < min_days:
        raise ValueError(f"Insufficient history: {len(data)} < {min_days}")
    if data.Volume.tail(20).mean() <= 0 or data.Volume.iloc[-1] <= 0:
        raise ValueError("No recent/latest trading volume")
    return data


def add_indicators(data, adjust_prices=True):
    data = data.copy()
    # Normalize past prices for corporate actions, anchored to the latest raw
    # quote. This avoids dividend/split gaps creating a false descending flag.
    if adjust_prices:
        factor = data["Adj Close"] / data.Close
        factor = factor / factor.iloc[-1]
        for column in ("Open", "High", "Low", "Close"):
            data[column] = data[column] * factor
    for days in (5, 10, 20, 60):
        data[f"MA{days}"] = data.Close.rolling(days).mean()
    for days in (5, 20):
        data[f"Volume_MA{days}"] = data.Volume.rolling(days).mean()
    for days in (5, 10, 20):
        data[f"return_{days}d"] = data.Close.pct_change(days, fill_method=None)
    for days in (20, 60):
        data[f"MA{days}_slope"] = data[f"MA{days}"].diff(5) / 5
    return data


def regression(values):
    y = np.asarray(values, dtype=float)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    total = np.sum((y - y.mean()) ** 2)
    r2 = 1 - np.sum((y - (intercept + slope * x)) ** 2) / total if total > 0 else 0
    return float(slope), float(intercept), float(max(0, r2))


def component_scores(result, config):
    clip = lambda value: float(np.clip(value, 0, 1))
    w = config.weights
    return {
        "uptrend": w.uptrend * clip((result["MA20"] / result["MA60"] - 1) / config.full_trend_spread),
        "flagpole": w.flagpole * clip(result["flagpole_return_pct"] / config.full_flagpole_return),
        "descending_flag": w.descending_flag * (
            clip(1 - result["slope_difference"] / config.slope_tolerance)
            + (result["high_r2"] + result["low_r2"]) / 2) / 2,
        "pullback": w.pullback * clip(1 - result["retracement"] / config.max_retracement),
        "volume": w.volume * clip((1 - result["volume_ratio"]) / (1 - config.full_volume_contraction)),
        "breakout": w.breakout if result["status"] == "BREAKOUT" else 0.0,
    }


def detect_patterns(data, config=BullFlagConfig()):
    """Input is validated history with indicators. Return all qualifying windows.

    Latest bar is a holdout: regress preceding 5–15 bars, then classify the
    holdout. FORMING stays inside the channel; an unconfirmed upside crossing
    remains FORMING with price_breakout=True. Only a first crossing is BREAKOUT.
    """
    latest = data.iloc[-1]
    if not (latest.Close > latest.MA20 > latest.MA60):
        return []
    results = []
    for length in range(config.min_flag_days, config.max_flag_days + 1):
        flag_start = len(data) - 1 - length
        pole_start = flag_start - config.flagpole_days
        if pole_start < 0:
            continue
        pole = data.iloc[pole_start:flag_start]
        flag = data.iloc[flag_start:-1]
        # Require the pole peak at the flag boundary, not an old rolling high.
        high = float(pole.High.iloc[-1])
        start_price = float(pole.Close.iloc[0])
        rise = high / start_price - 1
        if pole.High.max() > high or rise < config.min_flagpole_return:
            continue
        hs, hi, hr = regression(flag.High)
        ls, li, lr = regression(flag.Low)
        difference = abs(hs - ls) / max(abs(hs), abs(ls), 1e-12)
        upper, lower = hi + hs * length, li + ls * length
        if (hs >= 0 or ls >= 0 or difference > config.slope_tolerance
                or min(hr, lr) < config.min_regression_r2 or hi <= li or upper <= lower):
            continue
        trough = float(min(flag.Low.min(), latest.Low))
        retracement = (high - trough) / (high - start_price)
        if not (0 <= retracement <= config.max_retracement) or latest.Close < lower:
            continue
        pole_volume = float(pole.Volume.mean())
        baseline_volume = float(data.Volume.iloc[-21:-1].mean())
        if pole_volume <= 0 or baseline_volume <= 0:
            continue
        # Avoid calling a stock already above yesterday's resistance a fresh breakout.
        previous_inside = flag.Close.iloc[-1] <= hi + hs * (length - 1)
        if not previous_inside:
            continue
        price_breakout = latest.Close > upper
        breakout_ratio = float(latest.Volume / baseline_volume)
        confirmed = price_breakout and breakout_ratio > config.breakout_volume_multiplier
        result = dict(
            status="BREAKOUT" if confirmed else "FORMING", close=float(latest.Close),
            MA20=float(latest.MA20), MA60=float(latest.MA60),
            MA20_slope=float(latest.MA20_slope), MA60_slope=float(latest.MA60_slope),
            distance_MA20=float(latest.Close / latest.MA20 - 1),
            distance_MA60=float(latest.Close / latest.MA60 - 1),
            Volume_MA5=float(latest.Volume_MA5), Volume_MA20=float(latest.Volume_MA20),
            breakout_volume_baseline=baseline_volume,
            flagpole_start_price=start_price, flagpole_high=high,
            flagpole_return_pct=rise, flagpole_volume=pole_volume,
            pullback_pct=(trough / high - 1), retracement=float(retracement),
            high_slope=hs, low_slope=ls, slope_difference=difference,
            high_r2=hr, low_r2=lr, high_intercept=hi, low_intercept=li,
            channel_width=upper - lower, upper_flag_trendline=upper,
            lower_flag_trendline=lower, volume_ratio=float(flag.Volume.mean() / pole_volume),
            breakout_volume_ratio=breakout_ratio, price_breakout=bool(price_breakout),
            flag_days=length, flag_start=flag.index[0], flag_end=flag.index[-1],
            flagpole_start=pole.index[0], price_date=data.index[-1],
        )
        scores = component_scores(result, config)
        result.update({f"score_{key}": round(value, 2) for key, value in scores.items()})
        result["bull_flag_score"] = round(sum(scores.values()), 2)
        results.append(result)
    return results


def scan_universe(universe, histories, config=BullFlagConfig(), download_errors=None):
    records, issues, details = [], [], {}
    errors = download_errors or {}
    downloaded = analyzed = skipped = failures = 0
    scan_time = datetime.now(timezone.utc).isoformat()
    for stock in universe.to_dict("records"):
        ticker = stock["ticker"]
        if ticker not in histories:
            failures += 1
            issues.append(dict(ticker=ticker, stage="download", reason=errors.get(ticker, "No history")))
            continue
        downloaded += 1
        try:
            data = add_indicators(validate_history(histories[ticker], config.min_history_days))
            patterns = detect_patterns(data, config)
            analyzed += 1
            if patterns:
                details[ticker] = data
                records.extend(dict(stock, **pattern, scan_time=scan_time) for pattern in patterns)
        except ValueError as error:
            skipped += 1
            issues.append(dict(ticker=ticker, stage="validation", reason=str(error)))
        except Exception as error:
            failures += 1
            issues.append(dict(ticker=ticker, stage="analysis", reason=str(error)))
    for issue in issues:
        LOGGER.warning("%s %s: %s", issue["ticker"], issue["stage"], issue["reason"])
    frame = pd.DataFrame(records) if records else pd.DataFrame(columns=RESULT_COLUMNS + ["flag_days"])
    best = filter_candidates(frame, min_score=0, min_return=config.min_flagpole_return,
                             flag_days=(config.min_flag_days, config.max_flag_days),
                             max_retracement=config.max_retracement, max_volume_ratio=float("inf"))
    stats = dict(total=len(universe), downloaded=downloaded, analyzed=analyzed,
                 candidates=len(best), forming=int((best.status == "FORMING").sum()),
                 breakout=int((best.status == "BREAKOUT").sum()), skipped=skipped, errors=failures)
    return dict(patterns=frame, details=details, issues=issues, stats=stats, scan_time=scan_time)


def filter_candidates(patterns, market="All", min_score=60, min_return=0.15,
                      flag_days=(5, 15), max_retracement=0.5, max_volume_ratio=10.0, status="All"):
    """Filter before selecting each ticker's best window, so length filters stay correct."""
    if patterns.empty:
        return patterns.copy()
    frame = patterns[
        (patterns.bull_flag_score >= min_score) & (patterns.flagpole_return_pct >= min_return)
        & patterns.flag_days.between(*flag_days) & (patterns.retracement <= max_retracement)
        & (patterns.volume_ratio <= max_volume_ratio)]
    if market != "All":
        frame = frame[frame.market == market]
    if status != "All":
        frame = frame[frame.status == status]
    frame = frame.sort_values(["bull_flag_score", "ticker", "flag_days"], ascending=[False, True, True])
    frame = frame.drop_duplicates("ticker").reset_index(drop=True).copy()
    frame["rank"] = np.arange(1, len(frame) + 1)
    return frame
