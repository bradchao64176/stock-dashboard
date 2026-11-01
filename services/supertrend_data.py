"""Read existing daily cache; append missing Yahoo bars to an isolated cache.

Never INSERT/UPDATE/DELETE in the existing database. Never overwrite a cached
bar. Overlapping OHLC revisions fail closed instead of mixing price bases.
"""
from contextlib import closing
from pathlib import Path
import json
import math
import sqlite3
import numpy as np
import pandas as pd
from services.yahoo_history import download_histories
from services.liquidity_filter import calculate_trading_value

ROOT = Path(__file__).resolve().parents[1]
EXISTING_CACHE = ROOT / "data/unfilled_gap_prices.db"
STRATEGY_CACHE = ROOT / "data/supertrend_prices.db"
FIELDS = ["Open", "High", "Low", "Close", "Volume"]
SPLIT_CONTINUITY_LIMIT = .25


def cutoff_date(asof):
    now = pd.Timestamp(asof)
    now = now.tz_localize("Asia/Taipei") if now.tzinfo is None else now.tz_convert("Asia/Taipei")
    return now.normalize().tz_localize(None)-pd.Timedelta(days=int(now.hour < 14))


def request_start(config, cutoff):
    # Generous calendar span; sufficient actual completed bars are still checked.
    return cutoff-pd.Timedelta(days=math.ceil(config.required_bars*1.7)+90)


def normalize(history):
    if history is None or history.empty:
        raise ValueError("Empty Yahoo/cache history")
    if not isinstance(history.index, pd.DatetimeIndex) or history.index.hasnans:
        raise ValueError("Daily datetime index required")
    data = history.copy(deep=True)
    if data.index.tz is not None:
        data.index = data.index.tz_convert("Asia/Taipei").tz_localize(None)
    data.index = data.index.normalize()
    if data.index.has_duplicates or not set(FIELDS).issubset(data):
        raise ValueError("Duplicate daily dates or missing OHLCV")
    data[FIELDS] = data[FIELDS].apply(pd.to_numeric, errors="coerce")
    return data.sort_index()


def read_cache(path, tickers, start, end):
    histories, coverage, errors = {}, {}, {}
    if not Path(path).exists():
        return histories, coverage, errors
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True, timeout=30)) as db:
        db.execute("PRAGMA query_only=ON")
        has_coverage = db.execute("SELECT 1 FROM sqlite_master WHERE name='history_coverage'").fetchone()
        for ticker in tickers:
            try:
                rows = db.execute("SELECT date,payload FROM daily_prices WHERE ticker=? AND date>=? AND date<? ORDER BY date",
                                  (ticker,str(start.date()),str(end.date()))).fetchall()
                if rows:
                    frame = normalize(pd.DataFrame([json.loads(r[1]) for r in rows],index=pd.to_datetime([r[0] for r in rows])))
                    histories[ticker] = frame
                    coverage[ticker] = [(frame.index[0],frame.index[-1]+pd.Timedelta(days=1))]
                if has_coverage:
                    coverage.setdefault(ticker,[]).extend((pd.Timestamp(lo),pd.Timestamp(hi)) for lo,hi in db.execute(
                        "SELECT start,end FROM history_coverage WHERE ticker=?",(ticker,)))
            except (ValueError, TypeError, KeyError) as error:
                errors[ticker] = "CACHE_ERROR: " + str(error)
    return histories, coverage, errors


def missing_ranges(start, end, covered):
    cursor, result = start, []
    for lo, hi in sorted(covered):
        if hi <= cursor or lo >= end:
            continue
        if lo > cursor:
            result.append((cursor,min(lo,end)))
        cursor = max(cursor,hi)
    if cursor < end:
        result.append((cursor,end))
    return result


def load_prices(tickers, start, end, progress=None, existing_path=EXISTING_CACHE,
                cache_path=STRATEGY_CACHE, downloader=None, offline=False):
    start,end = pd.Timestamp(start).normalize(),pd.Timestamp(end).normalize()
    if start >= end:
        raise ValueError("Start must precede exclusive end")
    if Path(existing_path).resolve() == Path(cache_path).resolve():
        raise ValueError("Strategy cache must be separate from existing history")
    tickers = list(dict.fromkeys(tickers))
    base, coverage, errors = read_cache(existing_path,tickers,start,end)
    overlay, overlay_coverage, overlay_errors = read_cache(cache_path,tickers,start,end)
    errors.update(overlay_errors)
    histories = dict(base)
    for ticker, frame in overlay.items():
        combined = pd.concat([base.get(ticker,pd.DataFrame()),frame])
        histories[ticker] = combined.loc[~combined.index.duplicated(keep="first")].sort_index()
    plans = {}
    for ticker in tickers:
        covered = coverage.get(ticker,[])+overlay_coverage.get(ticker,[])
        for lo,hi in missing_ranges(start,end,covered):
            # Request a small overlap to detect revisions around cache boundaries.
            request_lo,request_hi = max(start,lo-pd.Timedelta(days=7)),min(end,hi+pd.Timedelta(days=7))
            plans.setdefault((request_lo,request_hi),[]).append(ticker)
    report = dict(cache_hits=len(histories), requested_stocks=len({t for ts in plans.values() for t in ts}),
                  downloaded_stocks=0, cache_only_stocks=len(tickers)-len({t for ts in plans.values() for t in ts}),
                  request_ranges=len(plans), offline=offline)
    downloaded_ids = set()
    if not offline and plans:
        Path(cache_path).parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(str(cache_path), timeout=30)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS daily_prices(ticker TEXT,date TEXT,payload TEXT,PRIMARY KEY(ticker,date))")
            db.execute("CREATE TABLE IF NOT EXISTS history_coverage(ticker TEXT,start TEXT,end TEXT,PRIMARY KEY(ticker,start,end))")
            for number, ((lo,hi),symbols) in enumerate(plans.items()):
                symbols = list(dict.fromkeys(symbols))
                if progress:
                    progress(number,len(plans),"Yahoo missing ranges")
                try:
                    fresh, failed = (downloader or download_histories)(symbols,start=str(lo.date()),end=str(hi.date()),actions=True)
                except Exception:
                    fresh,failed = {}, {t:"Yahoo request failed" for t in symbols}
                errors.update({t:"DOWNLOAD_ERROR: "+str(e) for t,e in failed.items()})
                for ticker in symbols:
                    if ticker not in fresh:
                        errors.setdefault(ticker,"DOWNLOAD_ERROR: empty/missing ticker")
                        continue
                    try:
                        frame=normalize(fresh[ticker]); frame=frame.loc[(frame.index>=lo)&(frame.index<hi)]
                        if frame.empty:
                            raise ValueError("No completed rows in requested range")
                        old=histories.get(ticker,pd.DataFrame())
                        overlap=old.index.intersection(frame.index)
                        if len(overlap) and not np.allclose(old.loc[overlap,FIELDS[:4]],frame.loc[overlap,FIELDS[:4]],rtol=1e-5,atol=1e-5,equal_nan=True):
                            errors[ticker]="DATA_CONSISTENCY_ERROR: Yahoo revised cached OHLC; cache preserved"
                            continue
                        # Reject bad fetched records, including unfinished bars, rather than caching them.
                        valid = np.isfinite(frame[FIELDS]).all(axis=1) & frame[FIELDS].gt(0).all(axis=1)
                        valid &= frame.High.ge(frame[["Open","Close","Low"]].max(axis=1)) & frame.Low.le(frame[["Open","Close"]].min(axis=1))
                        if not valid.all():
                            errors[ticker]="DOWNLOAD_ERROR: invalid/suspended OHLCV rows"
                        additions=frame.loc[valid & ~frame.index.isin(old.index)]
                        db.executemany("INSERT OR IGNORE INTO daily_prices VALUES (?,?,?)",
                                       [(ticker,str(day.date()),row.to_json()) for day,row in additions.iterrows()])
                        if valid.all():
                            db.execute("INSERT OR IGNORE INTO history_coverage VALUES (?,?,?)",(ticker,str(lo.date()),str(hi.date())))
                        db.commit()
                        # Preserve invalid rows in this in-memory scan so they break warm-up.
                        histories[ticker]=pd.concat([old,frame.loc[~frame.index.isin(old.index)]]).sort_index()
                        downloaded_ids.add(ticker)
                    except (ValueError,KeyError,TypeError) as error:
                        errors[ticker]="DOWNLOAD_ERROR: "+str(error)
            if progress:
                progress(len(plans),len(plans),"Yahoo missing ranges")
    report["downloaded_stocks"]=len(downloaded_ids)
    return histories,errors,report


def prepare_bars(history, sessions, cutoff):
    data=normalize(history)
    data=data.loc[data.index<=cutoff]
    if data.empty:
        raise ValueError("No completed data")
    data=data.reindex(sessions[(sessions>=data.index[0]) & (sessions<=data.index[-1])])
    valid=np.isfinite(data[FIELDS]).all(axis=1) & data[FIELDS].gt(0).all(axis=1)
    valid &= data.High.ge(data[["Open","Close","Low"]].max(axis=1)) & data.Low.le(data[["Open","Close"]].min(axis=1))
    # Yahoo normally already split-adjusts OHLC even with auto_adjust=False.
    # Do not apply a second split or erase valid daily EMA warm-up.
    # Reject unresolved large action-day discontinuities; never repair silently.
    if "Stock Splits" in data:
        split=data["Stock Splits"].fillna(0).ne(0)
        continuous=(data.Open/data.Close.shift()-1).abs().le(SPLIT_CONTINUITY_LIMIT)
        valid &= ~split | continuous
    data["valid_bar"]=valid
    data["trading_value"]=[calculate_trading_value(row,"shares")[0] for _,row in data.iterrows()]
    data["available_at"]=data.index+pd.Timedelta(hours=14)
    return data


def market_sessions(histories, cutoff):
    """Yahoo observed sessions, distinguishing broad flat zero-volume placeholders.

    At least two symbols must corroborate a no-trade date, with no positive
    volume anywhere in the supplied universe. This is Yahoo evidence, not an
    authoritative holiday calendar. Unreported recent weekdays remain expected.
    """
    observed, positive, placeholders, reported = set(), set(), {}, {}
    for history in histories.values():
        try:
            frame=normalize(history)
        except (ValueError,TypeError,KeyError):
            continue
        frame=frame.loc[frame.index<=cutoff]
        observed.update(frame.index)
        positive.update(frame.index[frame.Volume.gt(0) & frame.Close.gt(0)])
        flat=frame.Volume.eq(0) & frame[FIELDS[:4]].nunique(axis=1).eq(1) & frame.Close.gt(0)
        for day in frame.index:reported[day]=reported.get(day,0)+1
        for day in frame.index[flat]:placeholders[day]=placeholders.get(day,0)+1
    no_trade={day for day,count in placeholders.items() if count>=2 and count==reported[day] and day not in positive}
    return pd.DatetimeIndex(sorted(observed-no_trade)),pd.DatetimeIndex(sorted(no_trade))
