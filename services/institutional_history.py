"""Accumulate overlapping daily PChome snapshots without bridging unknown gaps."""
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

from services.pchome_scraper import CATEGORIES


def save_history(stock, database_path):
    result = deepcopy(stock)
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS institutional_history "
                           "(stock_id TEXT, category TEXT, records TEXT, PRIMARY KEY(stock_id, category))")
        for category in CATEGORIES:
            incoming = stock["history"][category]
            if not incoming:
                continue
            saved = connection.execute("SELECT records FROM institutional_history WHERE stock_id=? AND category=?",
                                       (stock["stock_id"], category)).fetchone()
            old = json.loads(saved[0]) if saved else []
            new_dates = {row["date"] for row in incoming}
            old_dates = {row["date"] for row in old}
            # A shared trading date establishes continuity between two daily windows.
            if old and not new_dates.intersection(old_dates):
                result["warnings"].append(f"{category}: history restarted because snapshots do not overlap.")
                old = []
            merged = {row["date"]: row for row in old}
            merged.update({row["date"]: row for row in incoming})
            rows = sorted(merged.values(), key=lambda row: row["date"], reverse=True)[:120]
            # Do not attach saved observations newer than this response's latest date.
            result["history"][category] = [r for r in rows if r["date"] <= incoming[0]["date"]]
            connection.execute("INSERT OR REPLACE INTO institutional_history VALUES (?, ?, ?)",
                               (stock["stock_id"], category, json.dumps(rows)))
    return result
