from __future__ import annotations

import re
from typing import Optional

from src.models import WatchlistStock


def match_stock(
    title: str,
    summary: Optional[str],
    stocks: list[WatchlistStock],
) -> Optional[WatchlistStock]:
    text = f"{title}\n{summary or ''}"
    folded = text.casefold()

    # Names are a stronger signal than numeric symbols and avoid matching stock
    # codes inside dates, prices, or unrelated larger numbers.
    for stock in stocks:
        names = (stock.company_name, *stock.aliases)
        if any(name.casefold() in folded for name in names):
            return stock

    for stock in stocks:
        if re.search(rf"(?<!\d){re.escape(stock.symbol)}(?!\d)", text):
            return stock
    return None
