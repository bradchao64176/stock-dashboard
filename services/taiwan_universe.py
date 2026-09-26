"""Official company rosters, deliberately excluding security-wide quote lists."""
import logging
import re

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)
SOURCES = {
    "TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "TPEx": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
}
COLUMNS = ["stock_code", "stock_name", "market", "ticker", "security_type"]


def is_common_stock(code):
    # Only company-roster entries with ordinary four-digit issuer codes.
    # ETF/ETN codes beginning with 0 and preferred/warrant suffixes are excluded.
    return bool(re.fullmatch(r"[1-9][0-9]{3}", code)) and not code.startswith("91")


def normalize_companies(payload, market, security_filter=is_common_stock):
    if market not in SOURCES or not isinstance(payload, list) or not payload:
        raise ValueError(f"{market}: invalid or empty company roster")
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"{market}: unexpected roster schema")
        code = str(item.get("公司代號", item.get("SecuritiesCompanyCode", ""))).strip()
        name = str(item.get("公司簡稱") or item.get("CompanyAbbreviation")
                   or item.get("公司名稱") or item.get("CompanyName") or "").strip()
        if security_filter(code) and name:
            rows.append(dict(stock_code=code, stock_name=name, market=market,
                             ticker=code + (".TW" if market == "TWSE" else ".TWO"),
                             security_type="common_stock"))
    if not rows:
        raise ValueError(f"{market}: no supported common stocks; check API schema")
    return pd.DataFrame(rows, columns=COLUMNS).drop_duplicates("ticker").sort_values("stock_code")


def fetch_taiwan_universe():
    """Return available markets and explicit errors; never mask a partial universe."""
    frames, errors = [], {}
    with requests.Session() as session:
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retry))
        for market, url in SOURCES.items():
            try:
                response = session.get(url, timeout=(10, 30))
                response.raise_for_status()
                frames.append(normalize_companies(response.json(), market))
            except (requests.RequestException, ValueError) as error:
                errors[market] = str(error)
                LOGGER.warning("Universe %s: %s", market, error)
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    return frame, errors
