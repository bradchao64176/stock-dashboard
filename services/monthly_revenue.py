"""Official monthly revenue, versioned in the existing OHLCV SQLite database.

Report-generation dates are NOT announcement dates. Unknown announcements use
first observation as conservative point-in-time availability, never period-end.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SOURCES = {"TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
           "TPEx": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"}


def taipei_now():
    return pd.Timestamp.now(tz="Asia/Taipei").tz_localize(None)


def number(value):
    try:
        result = float(str(value).replace(",", "").strip())
        return result if np.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def roc_period(value):
    digits = re.sub(r"\D", "", str(value))
    if len(digits) not in (5, 6):
        raise ValueError("Invalid revenue period")
    year, month = int(digits[:-2]), int(digits[-2:])
    year += 1911 if year < 1911 else 0
    return str(pd.Period(year=year, month=month, freq="M"))


def parse_revenue(rows, source):
    records = []
    for row in rows:
        code = str(row.get("公司代號", "")).strip()
        if not re.fullmatch(r"[1-9]\d{3}", code):
            continue
        revenue = number(row.get("營業收入-當月營收"))
        prior = number(row.get("營業收入-去年當月營收"))
        # Zero/negative prior bases do not support an interpretable growth ratio.
        yoy = (revenue - prior) / prior if revenue is not None and prior is not None and prior > 0 and revenue >= 0 else None
        records.append(dict(stock_code=code, year_month=roc_period(row["資料年月"]),
                            revenue=revenue, prior_year_revenue=prior, revenue_yoy=yoy,
                            source=source, report_date=str(row.get("出表日期", "")), revenue_publish_date=None))
    if not records:
        raise ValueError("Official revenue response contained no recognized records")
    return records


def load_monthly_revenue(cache_path, refresh=False, ttl_hours=24, now=None, session=None):
    now = pd.Timestamp(now) if now is not None else taipei_now()
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    errors = {}
    own_session = session is None
    session = session or requests.Session()
    if own_session:
        session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=.5, status_forcelist=[429, 500, 502, 503, 504])))
    try:
        with closing(sqlite3.connect(str(path), timeout=30)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS monthly_revenue (
                stock_code TEXT, year_month TEXT, revenue REAL, prior_year_revenue REAL,
                revenue_yoy REAL, source TEXT, report_date TEXT, revenue_publish_date TEXT,
                first_seen_at TEXT, updated_at TEXT, PRIMARY KEY(stock_code,year_month))""")
            db.execute("""CREATE TABLE IF NOT EXISTS monthly_revenue_versions (
                stock_code TEXT, year_month TEXT, version TEXT, payload TEXT,
                available_at TEXT, PRIMARY KEY(stock_code,year_month,version))""")
            db.execute("CREATE TABLE IF NOT EXISTS revenue_fetches (source TEXT PRIMARY KEY, fetched_at TEXT)")
            for market, url in SOURCES.items():
                cached = db.execute("SELECT fetched_at FROM revenue_fetches WHERE source=?", (url,)).fetchone()
                if cached and not refresh and now - pd.Timestamp(cached[0]) < pd.Timedelta(hours=ttl_hours):
                    continue
                try:
                    response = session.get(url, timeout=25)
                    response.raise_for_status()
                    records = parse_revenue(response.json(), url)
                    for record in records:
                        # Ignore report-generation changes when the economic data is unchanged.
                        version = hashlib.sha256(json.dumps({k: record[k] for k in ("revenue", "prior_year_revenue", "revenue_yoy")}, sort_keys=True).encode()).hexdigest()
                        previous = db.execute("SELECT version,available_at FROM monthly_revenue_versions WHERE stock_code=? AND year_month=? ORDER BY available_at DESC LIMIT 1",
                                              (record["stock_code"], record["year_month"])).fetchone()
                        unchanged = previous and previous[0].split(":")[0] == version
                        # A correction back to an older value is a new observed revision.
                        version = previous[0] if unchanged else version + ":" + now.isoformat()
                        record.update(first_seen_at=previous[1] if unchanged else now.isoformat(), updated_at=now.isoformat())
                        db.execute("INSERT OR IGNORE INTO monthly_revenue_versions VALUES (?,?,?,?,?)",
                                   (record["stock_code"], record["year_month"], version, json.dumps(record), record["first_seen_at"]))
                        db.execute("UPDATE monthly_revenue_versions SET payload=? WHERE stock_code=? AND year_month=? AND version=?",
                                   (json.dumps(record), record["stock_code"], record["year_month"], version))
                        db.execute("""INSERT INTO monthly_revenue VALUES (?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(stock_code,year_month) DO UPDATE SET revenue=excluded.revenue,
                            prior_year_revenue=excluded.prior_year_revenue,revenue_yoy=excluded.revenue_yoy,
                            source=excluded.source,report_date=excluded.report_date,
                            first_seen_at=excluded.first_seen_at,updated_at=excluded.updated_at""", tuple(record[k] for k in
                            ("stock_code", "year_month", "revenue", "prior_year_revenue", "revenue_yoy", "source", "report_date", "revenue_publish_date", "first_seen_at", "updated_at")))
                    db.execute("INSERT OR REPLACE INTO revenue_fetches VALUES (?,?)", (url, now.isoformat()))
                    db.commit()
                except Exception as error:
                    db.rollback()
                    errors[market] = str(error)
            rows = db.execute("SELECT payload,available_at FROM monthly_revenue_versions").fetchall()
            data = pd.DataFrame([dict(json.loads(payload), available_at=available) for payload, available in rows])
            return data, errors
    finally:
        if own_session:
            session.close()


def revenue_asof(records, stock_code, asof, max_age_months=2):
    """Use observed revisions only; unknown is distinct from zero growth."""
    unknown = dict(revenue_status="UNKNOWN", revenue_year_month=None, revenue=np.nan, revenue_yoy=np.nan,
                   revenue_updated_at=None, revenue_publish_date=None, revenue_available_at=None)
    if records is None or records.empty:
        return unknown
    cutoff = pd.Timestamp(asof)
    rows = records[(records.stock_code.astype(str) == str(stock_code)) & (pd.to_datetime(records.available_at) <= cutoff)]
    if rows.empty:
        return unknown
    row = rows.sort_values(["year_month", "available_at"]).iloc[-1]
    age = cutoff.to_period("M").ordinal - pd.Period(row.year_month, freq="M").ordinal
    status = "AVAILABLE" if 1 <= age <= max_age_months and pd.notna(row.revenue_yoy) else "STALE" if age > max_age_months else "UNKNOWN"
    return dict(revenue_status=status, revenue_year_month=row.year_month, revenue=row.revenue, revenue_yoy=row.revenue_yoy,
                revenue_updated_at=row.updated_at, revenue_publish_date=row.revenue_publish_date,
                revenue_available_at=row.available_at)
