"""Causal signals: only the detector prefix ending at T can produce a signal."""
import numpy as np
import pandas as pd

from src.bull_flag import add_indicators, detect_patterns, validate_history


def prepare_history(history, config):
    if history is None or history.empty:
        raise ValueError("Empty history")
    data = history.copy()
    if "Date" in data:
        data["Date"] = pd.to_datetime(data.Date, errors="coerce")
        data = data.set_index("Date")
    if not isinstance(data.index, pd.DatetimeIndex) or data.index.isna().any():
        raise ValueError("Invalid trading dates")
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    data.index = data.index.normalize()
    if data.index.duplicated().any():
        raise ValueError("Duplicate trading dates")
    data = data.sort_index()
    required = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    if any(column not in data for column in required):
        raise ValueError("Missing OHLCV/Adj Close columns")
    if len(data) < config.detector.min_history_days:
        raise ValueError("Insufficient history")
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = pd.Series(np.isfinite(data[required].to_numpy()).all(axis=1), index=data.index)
    valid &= (data[required[:-1]] > 0).all(axis=1) & (data.Volume > 0)
    valid &= (data.High >= data[["Open", "Close", "Low"]].max(axis=1))
    valid &= (data.Low <= data[["Open", "Close", "High"]].min(axis=1))
    data["valid_bar"] = valid
    data["valid_streak"] = valid.groupby((~valid).cumsum()).cumsum().astype(int)
    # Missing rows reset warmup; they are NOT deleted or interpolated. Previously
    # generated signals remain unchanged if a later row is invalid.
    for _, segment in data[valid].groupby((~valid).cumsum()[valid]):
        validate_history(segment, min_days=1)
        calculated = add_indicators(segment, adjust_prices=False)
        previous_close = segment.Close.shift(1)
        tr = pd.concat([segment.High - segment.Low, (segment.High - previous_close).abs(),
                        (segment.Low - previous_close).abs()], axis=1).max(axis=1)
        calculated["ATR"] = tr.rolling(config.atr_period).mean()
        for column in calculated.columns:
            if column not in data:
                data[column] = np.nan
            data.loc[segment.index, column] = calculated[column]
    return data


def generate_signals(data, stock, config, signal_start=None, signal_end=None):
    records = []
    warmup = max(config.detector.min_history_days,
                 config.detector.flagpole_days + config.detector.max_flag_days + 1,
                 config.atr_period + 1, 65)
    mask = ((data.valid_streak >= warmup) & (data.Close > data.MA20)
            & (data.MA20 > data.MA60) & (data.MA20_slope > 0))
    if config.require_breakout_volume:
        mask &= data.Volume > data.Volume.rolling(20).mean().shift(1) * config.detector.breakout_volume_multiplier
    if signal_start is not None:
        mask &= data.index >= pd.Timestamp(signal_start)
    if signal_end is not None:
        mask &= data.index <= pd.Timestamp(signal_end)
    for pos in np.flatnonzero(mask.to_numpy()):
        row = data.iloc[pos]
        date = data.index[pos]
        prefix = data.iloc[max(0, pos - warmup + 1):pos + 1]
        patterns = detect_patterns(prefix, config.detector)
        eligible = [p for p in patterns if p["price_breakout"]
                    and (not config.require_breakout_volume or p["status"] == "BREAKOUT")
                    and (not config.require_volume_contraction or p["volume_ratio"] < 1)
                    and p["bull_flag_score"] >= config.detector.min_bull_flag_score]
        if not eligible:
            continue
        best = max(eligible, key=lambda p: (p["bull_flag_score"], -p["flag_days"]))
        # Stop anchored to the flag before the breakout, known at signal close.
        flag_low = float(data.loc[best["flag_start"]:best["flag_end"], "Low"].min())
        records.append(dict(stock, **best, signal_date=date, signal_index=pos,
                            signal_id=f'{stock["ticker"]}:{date.date()}',
                            signal_close=float(row.Close), flag_swing_low=flag_low,
                            signal_atr=float(row.ATR)))
    return records
