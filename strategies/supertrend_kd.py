"""Causal Supertrend/EMA/KD calculations. No scanner, storage or network imports."""
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd

STRATEGY_ID = "SUPERTREND_EMA_KD_V1"


@dataclass(frozen=True)
class SupertrendConfig:
    timeframe: str = "Daily"
    ema_enabled: bool = True
    ema_period: int = 200
    warmup: int = 50
    atr_period: int = 10
    multiplier: float = 3.0
    kd_period: int = 9
    k_smoothing: int = 3
    d_smoothing: int = 3
    kd_ceiling: float = 40.0
    deviation_enabled: bool = True
    deviation_min: float = 0.0
    deviation_max: float = 10.0
    value_enabled: bool = True
    min_value: float = 100_000_000.0

    def __post_init__(self):
        for name in ("ema_period", "atr_period", "kd_period", "k_smoothing", "d_smoothing"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 1:
                raise ValueError(name + " must be a positive integer")
        if not isinstance(self.warmup, int) or self.warmup < 0:
            raise ValueError("Warm-up must be a nonnegative integer")
        if self.timeframe != "Daily":
            raise ValueError("Supertrend scanner supports Daily data only")
        for name in ("multiplier", "kd_ceiling", "deviation_min", "deviation_max", "min_value"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError("Nonfinite configuration")
        if self.multiplier <= 0 or not 0 < self.kd_ceiling <= 100 or self.min_value < 0:
            raise ValueError("Invalid multiplier, KD threshold or traded value")
        if self.deviation_min < 0 or self.deviation_max < self.deviation_min:
            raise ValueError("Deviation must satisfy 0 <= minimum <= maximum")

    @property
    def required_bars(self):
        if not self.ema_enabled:
            return max(self.atr_period + 1, self.kd_period + self.k_smoothing + self.d_smoothing + 1) + self.warmup
        return max(self.ema_period + self.warmup, self.atr_period + 1,
                   self.kd_period + self.k_smoothing + self.d_smoothing + 1)


def seeded_average(values, period, alpha):
    """SMA seed, then EMA/RMA. Invalid data restarts the warm-up."""
    result = np.full(len(values), np.nan)
    window, previous = [], np.nan
    for i, value in enumerate(np.asarray(values, dtype=float)):
        if not np.isfinite(value):
            window, previous = [], np.nan
        elif np.isnan(previous):
            window.append(value)
            if len(window) == period:
                previous = float(np.mean(window)); result[i] = previous
        else:
            previous += alpha * (value - previous); result[i] = previous
    return result


def calculate_indicators(history, config=SupertrendConfig()):
    """Raw Yahoo price basis; KD uses RSV with recursive K/D seeded at 50."""
    out = history.copy(deep=True)
    valid = out.get("valid_bar", pd.Series(True, index=out.index)).astype(bool)
    close, high, low = (out[c].where(valid) for c in ("Close", "High", "Low"))
    out["EMA"] = seeded_average(close, config.ema_period, 2 / (config.ema_period + 1))
    previous = close.shift()
    tr = pd.concat([high-low, (high-previous).abs(), (low-previous).abs()], axis=1).max(axis=1).where(valid)
    out["ATR"] = seeded_average(tr, config.atr_period, 1 / config.atr_period)
    basic_upper = ((high+low)/2 + config.multiplier*out.ATR).to_numpy()
    basic_lower = ((high+low)/2 - config.multiplier*out.ATR).to_numpy()
    upper, lower, trend = np.nan, np.nan, False
    lines, bullish = [], []
    prices = close.to_numpy()
    for i, price in enumerate(prices):
        if not np.isfinite(basic_upper[i]) or not np.isfinite(price):
            upper, lower, trend = np.nan, np.nan, False
            lines.append(np.nan); bullish.append(False); continue
        if np.isnan(upper):
            upper, lower, trend = basic_upper[i], basic_lower[i], False
        else:
            upper = basic_upper[i] if basic_upper[i] < upper or prices[i-1] > upper else upper
            lower = basic_lower[i] if basic_lower[i] > lower or prices[i-1] < lower else lower
            trend = price >= lower if trend else price > upper
        lines.append(lower if trend else upper); bullish.append(bool(trend))
    out["Supertrend"], out["supertrend_bullish"] = lines, bullish
    highest, lowest = high.rolling(config.kd_period).max(), low.rolling(config.kd_period).min()
    spread = highest-lowest
    rsv = (100*(close-lowest)/spread.where(spread.gt(0))).to_numpy()
    ks, ds, k, d = [], [], 50., 50.
    for value in rsv:
        if not np.isfinite(value):
            k, d = 50., 50.; ks.append(np.nan); ds.append(np.nan)
        else:
            k += (value-k)/config.k_smoothing
            d += (k-d)/config.d_smoothing
            ks.append(k); ds.append(d)
    out["K"], out["D"] = ks, ds
    out["kd_cross"] = (out.K > out.D) & (out.K.shift() <= out.D.shift())
    out["deviation_pct"] = 100*(out.Close/out.Supertrend.where(out.Supertrend.gt(0))-1)
    # Require a complete consecutive warm-up after invalid/suspended bars.
    out["ready"] = valid.rolling(config.required_bars).sum().eq(config.required_bars)
    out["ema_ok"] = (out.Close > out.EMA) if config.ema_enabled else True
    out["trend_ok"] = out.ready & out.ema_ok & out.supertrend_bullish & (out.Close > out.Supertrend)
    out["deviation_ok"] = out.deviation_pct.between(config.deviation_min, config.deviation_max) if config.deviation_enabled else True
    out["value_ok"] = out.trading_value.ge(config.min_value) if config.value_enabled else True
    out["kd_ok"] = out.kd_cross & out.K.lt(config.kd_ceiling) & out.D.lt(config.kd_ceiling)
    out["BUY"] = out.trend_ok & out.deviation_ok & out.value_ok & out.kd_ok
    return out
