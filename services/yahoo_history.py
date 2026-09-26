"""Bounded yfinance batches with failed-symbol retries, independent of Streamlit."""
import logging
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

LOGGER = logging.getLogger(__name__)


def completed_daily_bars(history, now=None):
    """Exclude today's potentially unfinished bar until 14:00 Taipei time."""
    now = now or datetime.now(timezone(timedelta(hours=8)))
    now = now.astimezone(timezone(timedelta(hours=8)))
    cutoff = now.date() if now.hour >= 14 else now.date() - timedelta(days=1)
    return history.loc[history.index.date <= cutoff].copy()


def split_history(frame, ticker, batch_size):
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        for level in range(frame.columns.nlevels):
            if ticker in frame.columns.get_level_values(level):
                return frame.xs(ticker, axis=1, level=level).dropna(how="all").copy()
        return pd.DataFrame()
    return frame.dropna(how="all").copy() if batch_size == 1 else pd.DataFrame()


def download_histories(tickers, batch_size=40, retries=2, progress=None, downloader=None,
                       period="1y", start=None, end=None, actions=False):
    """Fetch a period (default one year) or explicit inclusive start/exclusive end.

    yfinance's batch API internally issues requests per ticker; threads are capped.
    Retries only repeat failed symbols, not the successful portion of a batch.
    """
    if batch_size < 1 or retries < 0:
        raise ValueError("Invalid batch/retry settings")
    downloader = downloader or yf.download
    tickers = list(dict.fromkeys(tickers))
    histories, errors = {}, {}
    for offset in range(0, len(tickers), batch_size):
        pending = tickers[offset:offset + batch_size]
        for attempt in range(retries + 1):
            try:
                date_options = {"start": start, "end": end} if start is not None else {"period": period}
                frame = downloader(pending, **date_options, interval="1d", auto_adjust=False,
                                   group_by="ticker", threads=4, progress=False, timeout=20, actions=actions)
                batch_error = "Empty or missing Yahoo history"
            except Exception as error:
                frame, batch_error = None, str(error)
            failed = []
            for ticker in pending:
                try:
                    history = split_history(frame, ticker, len(pending))
                    if history.empty:
                        raise ValueError(batch_error)
                    histories[ticker] = completed_daily_bars(history)
                    errors.pop(ticker, None)
                except Exception as error:
                    failed.append(ticker)
                    errors[ticker] = str(error)
            pending = failed
            if not pending:
                break
            if attempt < retries:
                time.sleep(0.5 * (2 ** attempt))
        if progress:
            progress(min(offset + batch_size, len(tickers)), len(tickers))
    for ticker, error in errors.items():
        LOGGER.warning("Yahoo %s: %s", ticker, error)
    return histories, errors
