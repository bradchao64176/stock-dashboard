"""Pure candidate post-filter. No market IO, scanner changes or price writes."""
from dataclasses import dataclass
import math
import pandas as pd

DEFAULT_MIN_TRADING_VALUE = 100_000_000
TRADING_VALUE_INPUT_STEP = 10_000_000
YAHOO_VOLUME_UNIT = "shares"
# Only explicit monetary amount columns, never generic turnover ratios/volume.
OFFICIAL_AMOUNT_FIELDS = ("Trading Value", "Trade Value", "Turnover Amount", "TradingValue", "TradeValue", "成交金額", "成交值")


@dataclass(frozen=True)
class LiquidityConfig:
    enabled: bool = True
    min_trading_value: float = DEFAULT_MIN_TRADING_VALUE
    volume_unit: str = YAHOO_VOLUME_UNIT

    def __post_init__(self):
        if not math.isfinite(self.min_trading_value) or self.min_trading_value < 0:
            raise ValueError("Minimum trading value must be finite and nonnegative")
        if self.volume_unit not in ("shares", "lots"):
            raise ValueError("Volume unit must be explicit: shares or lots")


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def calculate_trading_value(bar, volume_unit=YAHOO_VOLUME_UNIT):
    if volume_unit not in ("shares", "lots"):
        raise ValueError("Unknown volume unit")
    if bar is None:
        return None, "UNKNOWN", None
    for field in OFFICIAL_AMOUNT_FIELDS:
        amount = _number(bar.get(field))
        if amount is not None and amount >= 0:
            return amount, "OFFICIAL", field
    close, volume = _number(bar.get("Close")), _number(bar.get("Volume"))
    if close is None or volume is None or close <= 0 or volume < 0:
        return None, "UNKNOWN", None
    amount = close * volume * (1000 if volume_unit == "lots" else 1)
    return (amount, "ESTIMATED", "Close * Volume" + (" * 1000" if volume_unit == "lots" else "")) if math.isfinite(amount) else (None, "UNKNOWN", None)


def format_trading_value(value):
    amount = _number(value)
    return "UNKNOWN" if amount is None else f"NT${amount / 1e8:.2f} 億"


def filter_trading_value(candidates, histories, config=LiquidityConfig(), date_column=None):
    """Live: last available bar. Historical: exact date only, never latest fallback."""
    out = candidates.copy(deep=True)
    values, statuses, sources, dates = [], [], [], []
    for candidate in out.to_dict("records"):
        history = histories.get(candidate.get("ticker"))
        bar = None
        day = None
        if history is not None and not history.empty and isinstance(history.index, pd.DatetimeIndex):
            index = history.index
            local = index.tz_convert("Asia/Taipei").tz_localize(None) if index.tz is not None else index
            if not local.hasnans and not local.normalize().has_duplicates:
                if date_column is None:
                    pos = local.argmax()
                    bar, day = history.iloc[pos], local[pos]
                elif pd.notna(candidate.get(date_column)):
                    target = pd.Timestamp(candidate[date_column])
                    if target.tzinfo is not None:
                        target = target.tz_convert("Asia/Taipei").tz_localize(None)
                    matches = (local.normalize() == target.normalize()).nonzero()[0]
                    if len(matches) == 1:
                        pos = matches[0]
                        bar, day = history.iloc[pos], local[pos]
        value, status, source = calculate_trading_value(bar, config.volume_unit)
        values.append(value); statuses.append(status); sources.append(source)
        dates.append(str(day.date()) if day is not None else None)
    out["trading_value"] = pd.Series(values, index=out.index, dtype=float)
    out["trading_value_status"] = statuses
    out["trading_value_source"] = sources
    out["trading_value_date"] = dates
    out["passes_trading_value_filter"] = out.trading_value.notna() & (out.trading_value >= config.min_trading_value)
    out["成交值"] = out.trading_value.map(format_trading_value)
    keep = out.passes_trading_value_filter if config.enabled else pd.Series(True, index=out.index)
    stats = dict(technical=len(out), below_minimum=int((out.trading_value.notna() & ~out.passes_trading_value_filter).sum()) if config.enabled else 0,
                 unknown_excluded=int(out.trading_value.isna().sum()) if config.enabled else 0,
                 remaining=int(keep.sum()), enabled=config.enabled, minimum=config.min_trading_value)
    return out.loc[keep].copy(), stats


def filter_backtest_signals(signal_set, config=LiquidityConfig()):
    filtered, stats = filter_trading_value(signal_set["signals"], signal_set["histories"], config, date_column="signal_date")
    return dict(signal_set, signals=filtered, stats=dict(signal_set["stats"], signals=len(filtered)), liquidity_stats=stats)
