"""Causal LazyBear-style Impulse MACD and independent crossover events."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.bull_flag import add_indicators
from src.bull_flag_gap import normalize_dates, observed_sessions


@dataclass(frozen=True)
class ImpulseConfig:
    ma_length: int = 34
    signal_length: int = 9
    cross_lookback_days: int = 5
    require_positive_impulse: bool = False
    require_close_above_ma20: bool = False
    require_ma20_above_ma60: bool = False
    require_ma20_rising: bool = False
    ma_slope_lookback: int = 5
    # Absolute indicator units; classification only, never changes crossover logic.
    zero_tolerance: float = 1e-10

    def __post_init__(self):
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in
               (self.ma_length, self.signal_length, self.ma_slope_lookback)):
            raise ValueError("Indicator lengths must be positive integers")
        if not isinstance(self.cross_lookback_days, int) or self.cross_lookback_days < 0:
            raise ValueError("Cross lookback must be a nonnegative integer")
        if not np.isfinite(self.zero_tolerance) or self.zero_tolerance < 0:
            raise ValueError("Invalid zero tolerance")


def smma(series, length):
    """SMA seed then Wilder recursion; a missing value resets warmup."""
    if length < 1:
        raise ValueError("SMMA length must be positive")
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    result = np.full(len(values), np.nan)
    count, total, previous = 0, 0., np.nan
    for i, value in enumerate(values):
        if not np.isfinite(value):
            count, total, previous = 0, 0., np.nan
            continue
        count += 1
        if count <= length:
            total += value
            if count == length:
                previous = total / length
        else:
            previous = (previous * (length - 1) + value) / length
        result[i] = previous
    return pd.Series(result, index=series.index)


def crossover(macd, signal):
    return (macd > signal) & (macd.shift(1) <= signal.shift(1))


def calculate_impulse(history, config=ImpulseConfig()):
    """Raw OHLC basis. Invalid bars reset all recursive calculations."""
    data = normalize_dates(history).sort_index()
    required = ["Open", "High", "Low", "Close", "Volume"]
    if data.empty or any(c not in data for c in required):
        raise ValueError("Missing OHLCV history")
    data[required] = data[required].apply(pd.to_numeric, errors="coerce")
    valid = (np.isfinite(data[required]).all(axis=1) & (data[required] > 0).all(axis=1)
             & (data.High >= data[["Open", "Close", "Low"]].max(axis=1))
             & (data.Low <= data[["Open", "Close"]].min(axis=1)))
    data["valid_bar"] = valid
    columns = ["SMMA_High", "SMMA_Low", "Impulse_ZLEMA", "Impulse_MACD", "Impulse_Signal", "Impulse_Histogram",
               "MA5", "MA10", "MA20", "MA60", "ma20_slope_pct", "Volume_MA20", "volume_ratio_20", "daily_return", "ATR"]
    for col in columns:
        data[col] = np.nan
    for _, segment in data.loc[valid].groupby((~valid).cumsum()[valid]):
        segment = add_indicators(segment, adjust_prices=False)
        src = (segment.High + segment.Low + segment.Close) / 3
        ema1 = src.ewm(span=config.ma_length, adjust=False).mean()
        ema2 = ema1.ewm(span=config.ma_length, adjust=False).mean()
        segment["Impulse_ZLEMA"] = 2 * ema1 - ema2
        segment["SMMA_High"] = smma(segment.High, config.ma_length)
        segment["SMMA_Low"] = smma(segment.Low, config.ma_length)
        z, high, low = segment.Impulse_ZLEMA, segment.SMMA_High, segment.SMMA_Low
        segment["Impulse_MACD"] = pd.Series(np.where(z > high, z - high, np.where(z < low, z - low, 0.)), index=segment.index).where(high.notna() & low.notna())
        segment["Impulse_Signal"] = segment.Impulse_MACD.rolling(config.signal_length).mean()
        segment["Impulse_Histogram"] = segment.Impulse_MACD - segment.Impulse_Signal
        segment["ma20_slope_pct"] = segment.MA20 / segment.MA20.shift(config.ma_slope_lookback) - 1
        segment["volume_ratio_20"] = segment.Volume / segment.Volume_MA20
        segment["daily_return"] = segment.Close / segment.Close.shift(1) - 1
        previous_close = segment.Close.shift(1)
        segment["ATR"] = pd.concat([segment.High - segment.Low, (segment.High - previous_close).abs(),
                                    (segment.Low - previous_close).abs()], axis=1).max(axis=1).rolling(14).mean()
        data.loc[segment.index, columns] = segment[columns]
    data["golden_cross"] = crossover(data.Impulse_MACD, data.Impulse_Signal)
    return data


def historical_cross_events(data, stock, config=ImpulseConfig()):
    """All historical signals with event-day-only filters; reusable by backtests.

    Execution/stop selection belongs to the existing engine, not this scanner.
    No current-price or surviving-signal filter enters these event records.
    """
    events = []
    for pos in np.flatnonzero(data.golden_cross.to_numpy()):
        row = data.iloc[pos]
        if config.require_positive_impulse and not row.Impulse_MACD > 0:
            continue
        if config.require_close_above_ma20 and not row.Close > row.MA20:
            continue
        if config.require_ma20_above_ma60 and not row.MA20 > row.MA60:
            continue
        if config.require_ma20_rising and not row.ma20_slope_pct > 0:
            continue
        zone = "NEAR_ZERO" if abs(row.Impulse_MACD) <= config.zero_tolerance else ("ABOVE_ZERO" if row.Impulse_MACD > 0 else "BELOW_ZERO")
        events.append(dict(stock, strategy="IMPULSE_MACD_GOLDEN_CROSS", signal_id=f'{stock["ticker"]}:IMPULSE:{data.index[pos].date()}',
                           signal_date=data.index[pos], signal_index=int(pos), golden_cross_date=data.index[pos],
                           signal_close=float(row.Close), cross_zone=zone, ma_length=config.ma_length,
                           signal_length=config.signal_length, **{name: float(row[name]) for name in
                           ("Impulse_MACD", "Impulse_Signal", "Impulse_Histogram", "MA20", "MA60", "ma20_slope_pct")}))
    return events


def scan_impulse_universe(universe, histories, config=ImpulseConfig(), download_errors=None):
    events, issues, details = [], [], {}
    calendar = observed_sessions(histories)
    stats = dict(total=len(universe), downloaded=len(histories), analyzed=0, skipped=0, errors=len(download_errors or {}), candidates=0)
    for stock in universe.to_dict("records"):
        ticker = stock["ticker"]
        try:
            if ticker in (download_errors or {}):
                raise ValueError("Incomplete refresh: " + str(download_errors[ticker]))
            history = histories.get(ticker)
            if history is None or history.empty:
                raise ValueError("No history")
            history = normalize_dates(history)
            history = history.reindex(calendar[calendar >= history.index.min()])
            data = calculate_impulse(history, config)
            if not data.valid_bar.iloc[-1] or not np.isfinite(data.Impulse_Signal.iloc[-1]):
                raise ValueError("Latest bar missing, invalid, or insufficient indicator warmup")
            stats["analyzed"] += 1
            recent = []
            for event in historical_cross_events(data, stock, config):
                age = len(data) - 1 - event["signal_index"]
                if age < max(1, config.cross_lookback_days):
                    recent.append(dict(event, trading_days_since_cross=age, current_close=float(data.Close.iloc[-1]),
                                       price_date=data.index[-1], current_impulse_macd=float(data.Impulse_MACD.iloc[-1]),
                                       current_impulse_signal=float(data.Impulse_Signal.iloc[-1]),
                                       current_histogram=float(data.Impulse_Histogram.iloc[-1])))
            if recent:
                details[ticker] = data
                events.extend(recent)
        except Exception as error:
            stats["skipped"] += 1
            issues.append(dict(ticker=ticker, reason=str(error)))
    frame = pd.DataFrame(events)
    candidates = frame.copy()
    if not candidates.empty:
        candidates = candidates.sort_values(["trading_days_since_cross", "ticker"]).drop_duplicates("ticker").reset_index(drop=True)
        candidates.insert(0, "rank", np.arange(1, len(candidates) + 1))
    stats["candidates"] = len(candidates)
    return dict(candidates=candidates, events=frame, details=details, issues=pd.DataFrame(issues), stats=stats,
                market_date=calendar[-1] if len(calendar) else None)
