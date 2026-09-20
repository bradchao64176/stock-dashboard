"""Transparent heuristic scores; these are not calibrated return forecasts."""
from __future__ import annotations

import math

from services.pchome_scraper import CATEGORIES


DEFAULT_WEIGHTS = {"fundamental": 25, "technical": 30, "news": 20, "institutional": 25}


def analyze_institutions(stock: dict, daily_volumes=None) -> dict:
    """daily_volumes optionally maps ISO dates to trading volume in lots.

    History must contain consecutive trading observations, newest first or sortable.
    Unknown values break streaks and invalidate any containing rolling window.
    """
    indicators = {}
    factors = {}
    as_of = stock.get("institutional_date")
    for category in CATEGORIES:
        rows = sorted(stock.get("history", {}).get(category, []), key=lambda r: r["date"], reverse=True)
        current = bool(rows and rows[0]["date"] == as_of)
        nets = [r.get("net") for r in rows]
        streak = None
        if current and nets[0] is not None:
            streak = 0
            for net in nets:
                if net is None or net <= 0:
                    break
                streak += 1
        item = {
            "available_days": len(rows), "consecutive_buy_days": streak,
            "streak_is_lower_bound": bool(streak and (streak == len(nets) or nets[streak] is None)),
        }
        for days in (5, 10, 20):
            window = nets[:days]
            item[f"net_{days}d"] = sum(window) if current and len(window) == days and None not in window else None
        indicators[category] = item
        if current and nets[0] is not None and category != "institutional_total":
            factors[f"{category}_net"] = _sign(nets[0])
        if streak is not None and category != "institutional_total":
            # Signed streak: distinguish sustained selling from no buying streak.
            signed_days = 0
            direction = _sign(nets[0])
            for net in nets:
                if net is None or not direction or _sign(net) != direction:
                    break
                signed_days += direction
            factors[f"{category}_streak"] = max(-1, min(1, signed_days / 5))
    for category in ("foreign", "institutional_total"):
        for days in (5, 20):
            net = indicators[category][f"net_{days}d"]
            if net is not None:
                factors[f"{category}_{days}d"] = _sign(net)

    total = stock.get("institutional_total")
    volume = (daily_volumes or {}).get(as_of)
    if volume is None and stock.get("quote_date") == as_of:
        volume = stock.get("volume")
    ratio = None
    if total and total.get("date") == as_of and total.get("net") is not None and volume is not None and volume > 0:
        ratio = total["net"] / volume
        factors["institutional_volume_ratio"] = max(-1, min(1, ratio / 0.20))
    score = round(50 + 50 * sum(factors.values()) / len(factors), 2) if factors else None
    return {"as_of": as_of, "indicators": indicators, "institutional_buy_ratio": ratio,
            "score": score, "interpretation": score_label(score), "factors": factors,
            "factor_coverage": len(factors) / 11}


def _sign(value):
    return (value > 0) - (value < 0)


def score_label(score):
    if score is None:
        return "Unavailable"
    for threshold, label in ((80, "Strong Institutional Buying"), (60, "Positive"),
                             (40, "Neutral"), (20, "Negative")):
        if score >= threshold:
            return label
    return "Strong Institutional Selling"


def combine_stock_scores(scores: dict, weights=None) -> dict:
    """Combine 0–100 components; disclose missing components and weight coverage."""
    weights = DEFAULT_WEIGHTS.copy() if weights is None else dict(weights)
    if not weights or set(weights) - set(DEFAULT_WEIGHTS):
        raise ValueError("Use fundamental, technical, news, and institutional weights.")
    if any(not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError("Weights must be finite nonnegative numbers.")
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("At least one weight must be positive.")
    available = {}
    for key, weight in weights.items():
        value = scores.get(key)
        if value is not None:
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"{key} score must be between 0 and 100.")
            if weight:
                available[key] = value
    covered = sum(weights[key] for key in available)
    return {
        "score": round(sum(available[k] * weights[k] for k in available) / covered, 2) if covered else None,
        "coverage": covered / total, "components": available,
        "missing": [key for key, weight in weights.items() if weight and key not in available],
        "effective_weights": {key: weights[key] / covered for key in available},
    }
