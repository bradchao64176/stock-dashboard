"""Read-only price adapter. Optional downloads remain in memory."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import numpy as np
import pandas as pd
from services.liquidity_filter import calculate_trading_value

ROOT = Path(__file__).resolve().parents[1]
PRICE_DB = ROOT / "data" / "unfilled_gap_prices.db"


def read_histories(tickers=None, start=None, end=None, path=PRICE_DB):
    if not Path(path).exists():
        raise ValueError("Daily cache does not exist")
    result = {}
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True, timeout=30)) as db:
        db.execute("PRAGMA query_only=ON")
        symbols = tickers if tickers is not None else [r[0] for r in db.execute("SELECT DISTINCT ticker FROM daily_prices ORDER BY ticker")]
        for ticker in symbols:
            rows = db.execute("SELECT date,payload FROM daily_prices WHERE ticker=? AND date>=? AND date<=? ORDER BY date",
                              (ticker, str(start or "1900-01-01"), str(end or "9999-12-31"))).fetchall()
            if rows:
                result[ticker] = pd.DataFrame([json.loads(r[1]) for r in rows], index=pd.to_datetime([r[0] for r in rows]))
    return result


def completed_cutoff(asof):
    now = pd.Timestamp(asof)
    now = now.tz_localize("Asia/Taipei") if now.tzinfo is None else now.tz_convert("Asia/Taipei")
    return now.normalize().tz_localize(None) - pd.Timedelta(days=int(now.hour < 14))


def prepare_daily(history, asof, calendar):
    data = history.copy(deep=True)
    if not isinstance(data.index, pd.DatetimeIndex) or data.index.has_duplicates or data.index.hasnans:
        raise ValueError("Unique valid datetime index required")
    if data.index.tz is not None:
        data.index = data.index.tz_convert("Asia/Taipei").tz_localize(None)
    data.index = data.index.normalize()
    if data.index.has_duplicates:
        raise ValueError("Multiple bars per session")
    data = data.loc[data.index <= completed_cutoff(asof)].sort_index()
    required = ["Open", "High", "Low", "Close", "Volume"]
    if data.empty or any(c not in data for c in required):
        raise ValueError("Missing completed OHLCV data")
    sessions = calendar.sessions(data.index.min(), data.index.max())
    data = data.reindex(sessions)
    data[required] = data[required].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(data[required]).all(axis=1) & (data[required] > 0).all(axis=1)
    valid &= data.High >= data[["Open", "Close", "Low"]].max(axis=1)
    valid &= data.Low <= data[["Open", "Close"]].min(axis=1)
    # Raw prices: action bars reset structure rather than manufacture breaks.
    for column in ("Dividends", "Stock Splits"):
        if column in data:
            valid &= data[column].fillna(0).eq(0)
    data["valid_bar"] = valid
    data["trading_value"] = [calculate_trading_value(row, "shares")[0] for _, row in data.iterrows()]
    data["available_at"] = data.index + pd.Timedelta(hours=14)
    return data
