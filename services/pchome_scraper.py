"""PChome quotes and daily institutional holdings. All volumes are in lots (張)."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from io import StringIO
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


CATEGORIES = {
    "foreign": "外資持股",
    "investment_trust": "投信持股",
    "dealer": "自營商持股",
    "institutional_total": "合計",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
}
FIELDS = {
    "買進張數": "buy", "賣出張數": "sell", "買賣超張數": "net",
    "持有張數": "shares_held", "持股比率": "ownership_percent",
}


class PChomeParseError(ValueError):
    """The response does not contain a usable quote for the requested stock."""


def normalize_stock_id(stock_id: str) -> str:
    stock_id = str(stock_id).strip().upper()
    # Includes Taiwan ETF codes such as 00679B and 00981A; preserve leading zeros.
    if not re.fullmatch(r"(?:[0-9]{4,6}|[0-9]{4,5}[A-Z])", stock_id):
        raise ValueError("Enter a Taiwan stock code such as 2409, 0050, or 00981A.")
    return stock_id


def stock_url(stock_id: str) -> str:
    return f"https://pchome.megatime.com.tw/stock/sto1/sid{normalize_stock_id(stock_id)}.html"


def number(value):
    """Return a finite JSON number or None; never convert missing data to zero."""
    text = re.sub(r"\s+", "", str(value)).replace(",", "").replace("%", "")
    text = text.replace("−", "-").replace("▲", "").replace("▼", "")
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return None
    result = float(text)
    if not math.isfinite(result):
        return None
    return int(result) if result.is_integer() else result


def _compact(value):
    return re.sub(r"\s+", "", str(value))


def _frame(table):
    # Find the header by its cells, not by a table/row number.
    rows = table.find_all("tr")
    header = next((i for i, row in enumerate(rows) if row.find("th")), None)
    if header is None:
        return None
    try:
        return pd.read_html(StringIO(str(table)), header=header, flavor="lxml")[0]
    except (ValueError, IndexError):
        return None


def parse_stock(html: str, stock_id: str) -> dict:
    stock_id = normalize_stock_id(stock_id)
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1 .corp-name") or soup.find("h1")
    title = heading.get_text(" ", strip=True) if heading else ""
    match = re.search(r"^(.*?)\s*\(\s*([0-9A-Z]+)\s*\)", title)
    if not match or match.group(2) != stock_id:
        raise PChomeParseError("Stock not found, page blocked, or PChome page structure changed.")
    price_node = soup.select_one(".stock-data .data_close")
    price = number(price_node.get_text()) if price_node else None
    if price is None:
        raise PChomeParseError("PChome did not return a valid current price.")
    result = {
        "stock_id": stock_id, "name": _compact(match.group(1)), "price": price,
        "change": None, "change_percent": None, "volume": None,
        "open": None, "high": None, "low": None, "previous_close": None,
        "source": "PChome", "url": stock_url(stock_id), "volume_unit": "lots",
        "quote_date": None, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "history": {key: [] for key in CATEGORIES}, "warnings": [],
    }
    for node in soup.select(".stock-data .data_diff"):
        text = node.get_text(strip=True)
        result["change_percent" if "%" in text else "change"] = number(text)

    for table in soup.find_all("table"):
        # Ignore outer layout tables containing other tables.
        if table.find("table"):
            continue
        frame = _frame(table)
        if frame is None or frame.empty:
            continue
        frame.columns = [_compact(c) for c in frame.columns]
        if {"成交張", "開盤", "昨收"}.issubset(frame.columns):
            for label, key in {"成交張": "volume", "開盤": "open", "最高": "high",
                               "最低": "low", "昨收": "previous_close", "漲跌": "change"}.items():
                if label in frame.columns:
                    result[key] = number(frame.iloc[0][label])
            continue
        if not {"日期", "買賣超張數"}.issubset(frame.columns):
            continue
        caption = _compact(table.get_text(" ", strip=True))
        category = next((key for key, label in CATEGORIES.items() if label in caption), None)
        if category is None:
            previous = table.find_previous(["h2", "h3", "h4"])
            caption = _compact(previous.get_text()) if previous else ""
            category = next((key for key, label in CATEGORIES.items() if label in caption), None)
        if category is None:
            continue
        records = {}
        for _, row in frame.iterrows():
            raw_date = str(row["日期"]).strip().replace("/", "-")
            try:
                date = datetime.strptime(raw_date, "%Y-%m-%d").date().isoformat()
            except ValueError:
                continue
            record = {"date": date}
            for column, key in FIELDS.items():
                record[key] = number(row[column]) if column in frame.columns else None
            # Keep published net values: rounded buy - sell may differ by one lot.
            records[date] = record
        result["history"][category] = sorted(records.values(), key=lambda r: r["date"], reverse=True)

    dates = [rows[0]["date"] for rows in result["history"].values() if rows]
    result["institutional_date"] = max(dates) if dates else None
    for category, rows in result["history"].items():
        result[category] = rows[0] if rows else None
        if not rows:
            result["warnings"].append(f"No daily {category.replace('_', ' ')} table was found.")
        elif any(r[field] is None for r in rows for field in FIELDS.values()):
            result["warnings"].append(f"Some {category.replace('_', ' ')} values are unavailable or invalid.")
    result["warnings"].append(
        "PChome does not identify the quote date here; the institutional/volume ratio "
        "requires volume from a confirmed matching trading date."
    )
    return result


def fetch_stock(stock_id: str) -> dict:
    """Fetch a public page with a 15-second timeout; return JSON-compatible data.

    Request exceptions propagate to callers. Parsing and validation errors are ValueError.
    No cache or UI dependency is imposed on non-Streamlit callers.
    """
    stock_id = normalize_stock_id(stock_id)
    url = stock_url(stock_id)
    with requests.Session() as session:
        session.headers.update(HEADERS)
        response = session.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        form = soup.select_one("form#submit_form")
        if form is not None and form.select_one('input[name="is_check"][value="1"]'):
            # Follow only the site's known same-page form, never an arbitrary action.
            if urljoin(url, form.get("action", "")) != url:
                raise PChomeParseError("Unexpected PChome page-loading form destination.")
            response = session.post(url, data={"is_check": "1"}, timeout=15)
            response.raise_for_status()
        # BeautifulSoup reads the HTML charset instead of requests' ISO-8859-1 default.
        return parse_stock(response.content, stock_id)
