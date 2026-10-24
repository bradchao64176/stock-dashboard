import pandas as pd
from .data import completed_cutoff


def weekly_bars(daily, asof, calendar):
    rows, dates = [], []
    cutoff = completed_cutoff(asof)
    for period, bars in daily.groupby(daily.index.to_period("W-FRI")):
        start = period.end_time.normalize() - pd.Timedelta(days=4)
        end = period.end_time.normalize()
        expected = calendar.sessions(start, end)
        if expected.empty or end > cutoff:
            continue
        # Missing sessions produce an invalid candle, not a shorter fabricated week.
        complete = bars.index.equals(expected) and bool(bars.valid_bar.all())
        rows.append(dict(Open=bars.Open.iloc[0], High=bars.High.max(), Low=bars.Low.min(),
                         Close=bars.Close.iloc[-1], Volume=bars.Volume.sum(min_count=1),
                         trading_value=bars.trading_value.sum(min_count=1), valid_bar=complete,
                         available_at=end+pd.Timedelta(hours=14)))
        dates.append(expected[-1])
    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates))


def volume_ratios(data, period):
    """Prior completed bars only; invalid bars reset the rolling window."""
    return data.Volume.where(data.valid_bar).shift(1).rolling(period, min_periods=period).mean()
