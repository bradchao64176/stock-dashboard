"""Exact-range SQLite cache around the shared Yahoo history downloader."""
from contextlib import closing
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import sqlite3
import time
import json

import pandas as pd

from services.yahoo_history import download_histories


def load_incremental_histories(tickers, start, end, cache_path, progress=None, refresh_lookback_months=0):
    """Daily-bar cache in the existing database; end is exclusive.

    Import existing action-inclusive snapshots once per symbol. Only request
    uncovered intervals; successful coverage includes non-trading dates. Failed
    downloads are never marked covered. Existing snapshot callers remain intact.
    An opt-in refresh window widens short missing tails to include recent daily
    sessions; older cached rows remain available for indicator warmup.
    """
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    # Do not mark an unfinished trading day as covered.
    now = pd.Timestamp.now(tz="Asia/Taipei")
    available_end = now.normalize().tz_localize(None) + pd.Timedelta(days=int(now.hour >= 14))
    end = min(end, available_end)
    if start >= end:
        raise ValueError("Historical start must precede the completed-bar cutoff")
    histories, errors, requests = {}, {}, {}
    with closing(sqlite3.connect(str(path), timeout=30)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS daily_prices (ticker TEXT, date TEXT, payload TEXT, PRIMARY KEY(ticker,date))")
        db.execute("CREATE TABLE IF NOT EXISTS history_coverage (ticker TEXT, start TEXT, end TEXT, PRIMARY KEY(ticker,start,end))")
        def save(ticker, frame, lo, hi):
            frame = frame.copy()
            frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
            db.executemany("INSERT INTO daily_prices VALUES (?,?,?) ON CONFLICT(ticker,date) DO UPDATE SET payload=excluded.payload",
                           [(ticker, str(day.date()), row.to_json()) for day, row in frame.iterrows() if lo <= day < hi])
            db.execute("INSERT OR IGNORE INTO history_coverage VALUES (?,?,?)", (ticker, str(lo.date()), str(hi.date())))
        legacy = db.execute("SELECT name FROM sqlite_master WHERE name='price_snapshots_actions'").fetchone()
        for ticker in dict.fromkeys(tickers):
            coverage = db.execute("SELECT start,end FROM history_coverage WHERE ticker=? ORDER BY start", (ticker,)).fetchall()
            if not coverage and legacy:
                snapshots = db.execute("SELECT start_date,end_date,payload,stored_at FROM price_snapshots_actions WHERE ticker=? ORDER BY stored_at", (ticker,)).fetchall()
                for lo, hi, payload, stored_at in snapshots:
                    frame = pd.read_json(StringIO(payload), orient="split")
                    # Preserve successful coverage of holidays, but never an unfinished day.
                    if not frame.empty:
                        lo = pd.Timestamp(lo)
                        fetched = pd.Timestamp(stored_at, unit="s", tz="UTC").tz_convert("Asia/Taipei")
                        fetched_end = fetched.normalize().tz_localize(None) + pd.Timedelta(days=int(fetched.hour >= 14))
                        hi = min(pd.Timestamp(hi), fetched_end)
                        save(ticker, frame, lo, hi)
                coverage = db.execute("SELECT start,end FROM history_coverage WHERE ticker=? ORDER BY start", (ticker,)).fetchall()
            cursor = start
            for lo, hi in coverage:
                lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
                if hi <= cursor or lo >= end:
                    continue
                if cursor < lo:
                    requests.setdefault((str(cursor.date()), str(min(lo, end).date())), []).append(ticker)
                cursor = max(cursor, hi)
            if cursor < end:
                requests.setdefault((str(cursor.date()), str(end.date())), []).append(ticker)
        if refresh_lookback_months:
            widened = {}
            for (lo, hi), symbols in requests.items():
                window_start = pd.Timestamp(hi) - pd.DateOffset(months=refresh_lookback_months)
                lo = str(max(start, min(pd.Timestamp(lo), window_start)).date())
                widened.setdefault((lo, hi), []).extend(symbols)
            requests = {bounds: list(dict.fromkeys(symbols)) for bounds, symbols in widened.items()}
        for (lo, hi), symbols in requests.items():
            downloaded, failed = download_histories(symbols, start=lo, end=hi, actions=True, progress=progress)
            errors.update(failed)
            for ticker, frame in downloaded.items():
                if not frame.empty:
                    save(ticker, frame, pd.Timestamp(lo), pd.Timestamp(hi))
            db.commit()
        for ticker in dict.fromkeys(tickers):
            rows = db.execute("SELECT date,payload FROM daily_prices WHERE ticker=? AND date>=? AND date<? ORDER BY date",
                              (ticker, str(start.date()), str(end.date()))).fetchall()
            if rows:
                histories[ticker] = pd.DataFrame([json.loads(row[1]) for row in rows], index=pd.to_datetime([row[0] for row in rows]))
        db.commit()
    return histories, errors


def load_backtest_histories(tickers, start, end, cache_path, refresh=False, ttl=86400, progress=None, actions=False):
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    histories, errors, pending = {}, {}, []
    key_start, key_end = str(start), str(end)
    fetched_at = datetime.now(timezone.utc).isoformat()
    table = "price_snapshots_actions" if actions else "price_snapshots"
    with closing(sqlite3.connect(str(path), timeout=30)) as db:
        db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
            ticker TEXT, start_date TEXT, end_date TEXT, stored_at REAL, fetched_at TEXT, payload TEXT,
            PRIMARY KEY (ticker, start_date, end_date))""")
        for ticker in dict.fromkeys(tickers):
            row = db.execute(f"SELECT stored_at, payload FROM {table} WHERE ticker=? AND start_date=? AND end_date=?",
                             (ticker, key_start, key_end)).fetchone()
            if row and not refresh and time.time() - row[0] < ttl:
                try:
                    frame = pd.read_json(StringIO(row[1]), orient="split")
                    frame.index = pd.to_datetime(frame.index)
                    histories[ticker] = frame
                    continue
                except (ValueError, TypeError):
                    pass
            pending.append(ticker)
        if pending:
            downloaded, errors = download_histories(pending, start=key_start, end=key_end, progress=progress, actions=actions)
            histories.update(downloaded)
            for ticker, frame in downloaded.items():
                db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?, ?, ?, ?)",
                           (ticker, key_start, key_end, time.time(), fetched_at,
                            frame.to_json(orient="split", date_format="iso", double_precision=15)))
        db.commit()
    return histories, errors
