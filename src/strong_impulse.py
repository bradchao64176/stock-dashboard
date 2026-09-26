"""Explainable strong preset, sharing the existing causal Impulse detector."""
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from services.monthly_revenue import revenue_asof, taipei_now
from src.impulse_macd import ImpulseConfig, scan_impulse_universe


@dataclass(frozen=True)
class StrongConfig:
    min_volume_ratio_20: float = 1.5
    volume_evaluation_mode: str = "CROSS_DAY"
    min_revenue_yoy: float = .10
    require_positive_cross_day_return: bool = False
    max_revenue_age_months: int = 2
    extreme_volume_ratio: float = 3.

    def __post_init__(self):
        if self.volume_evaluation_mode not in ("CROSS_DAY", "CURRENT", "CROSS_DAY_OR_CURRENT", "CROSS_DAY_AND_CURRENT"):
            raise ValueError("Unknown volume evaluation mode")
        if not np.isfinite(self.min_volume_ratio_20) or self.min_volume_ratio_20 <= 0 or not np.isfinite(self.min_revenue_yoy):
            raise ValueError("Invalid strong thresholds")
        if self.max_revenue_age_months < 1 or self.extreme_volume_ratio <= 0:
            raise ValueError("Invalid freshness/volume settings")


def describe_event(event, data, revenue, config=StrongConfig(), asof=None, current_pos=None):
    """Current trend for screening; pass current_pos=signal_index for backtests."""
    pos = int(event["signal_index"])
    cross = data.iloc[pos]
    current_pos = len(data) - 1 if current_pos is None else current_pos
    current = data.iloc[current_pos]
    result = dict(event)
    for name, value in (("cross_date_impulse_macd", cross.Impulse_MACD), ("cross_date_impulse_signal", cross.Impulse_Signal),
                        ("cross_date_impulse_histogram", cross.Impulse_Histogram), ("cross_day_volume", cross.Volume),
                        ("cross_day_volume_ma20", cross.Volume_MA20), ("cross_day_volume_ratio_20", cross.volume_ratio_20),
                        ("current_volume_ratio_20", current.volume_ratio_20), ("current_volume", current.Volume),
                        ("current_volume_ma20", current.Volume_MA20), ("cross_day_return_pct", cross.daily_return),
                        ("current_day_return_pct", current.daily_return), ("current_close", current.Close),
                        ("MA20", current.MA20), ("MA60", current.MA60), ("MA20_Slope_Pct", current.ma20_slope_pct)):
        result[name] = float(value)
    result.update(revenue_asof(revenue, event["stock_code"], asof if asof is not None else taipei_now(), config.max_revenue_age_months))
    a, b = float(cross.volume_ratio_20), float(current.volume_ratio_20)
    volumes = {"CROSS_DAY": [a], "CURRENT": [b], "CROSS_DAY_OR_CURRENT": [a, b], "CROSS_DAY_AND_CURRENT": [a, b]}[config.volume_evaluation_mode]
    checks = [np.isfinite(v) and v >= config.min_volume_ratio_20 for v in volumes]
    volume_pass = any(checks) if config.volume_evaluation_mode == "CROSS_DAY_OR_CURRENT" else all(checks)
    effective = (max if config.volume_evaluation_mode == "CROSS_DAY_OR_CURRENT" else min)(volumes) if all(np.isfinite(v) for v in volumes) else (max([v for v in volumes if np.isfinite(v)], default=np.nan) if config.volume_evaluation_mode == "CROSS_DAY_OR_CURRENT" else np.nan)
    result["cross_zone"] = "ABOVE_ZERO" if cross.Impulse_MACD > 0 else ("BELOW_ZERO" if cross.Impulse_MACD < 0 else "NEAR_ZERO")
    conditions = dict(impulse_golden_cross=bool(data.golden_cross.iloc[pos]), above_zero=bool(cross.Impulse_MACD > 0),
                      close_above_ma20=bool(current.Close > current.MA20), ma20_above_ma60=bool(current.MA20 > current.MA60),
                      ma20_rising=bool(current.ma20_slope_pct > 0), volume_expansion=bool(volume_pass),
                      revenue_growth=bool(result["revenue_status"] == "AVAILABLE" and result["revenue_yoy"] > config.min_revenue_yoy))
    if config.require_positive_cross_day_return:
        conditions["positive_cross_day_return"] = bool(cross.daily_return > 0)
    result.update({"condition_" + key: value for key, value in conditions.items()})
    result.update(failed_conditions=[key for key, value in conditions.items() if not value],
                  strong_golden_cross=all(conditions.values()), volume_evaluation_mode=config.volume_evaluation_mode,
                  evaluated_volume_ratio_20=effective, trend_date=data.index[current_pos],
                  volume_flag="EXTREME_VOLUME" if any(v > config.extreme_volume_ratio for v in volumes if np.isfinite(v)) else "")
    clip = lambda x: float(np.clip(x, 0, 1)) if np.isfinite(x) else 0.
    components = dict(impulse_cross_quality=20. * conditions["impulse_golden_cross"],
                      impulse_positive_zone=10. * conditions["above_zero"],
                      trend_quality=20. / 3 * sum(conditions[k] for k in ("close_above_ma20", "ma20_above_ma60", "ma20_rising")),
                      volume_expansion=20. * clip((effective - 1) / 2),
                      revenue_growth=20. * clip(result["revenue_yoy"] / .5) if result["revenue_status"] == "AVAILABLE" else 0.,
                      momentum_price_strength=10. * clip(cross.daily_return / .05))
    result.update({"score_" + key: value for key, value in components.items()})
    result["strong_golden_cross_score"] = round(sum(components.values()), 2)
    result["status"] = "STRONG_GOLDEN_CROSS" if result["strong_golden_cross"] else "NOT_STRONG"
    return result


def rank_strong(events, strong_only=True):
    if events.empty:
        return events.copy()
    result = events[events.strong_golden_cross] if strong_only else events
    result = result.sort_values(["strong_golden_cross_score", "golden_cross_date"], ascending=[False, False]).drop_duplicates("ticker").reset_index(drop=True).copy()
    result["rank"] = np.arange(1, len(result) + 1)
    return result


def scan_strong_universe(universe, histories, revenue, impulse=ImpulseConfig(), strong=StrongConfig(), download_errors=None, asof=None):
    # Inclusive age <= N, while the legacy pure strategy retains N sessions.
    broad = replace(impulse, cross_lookback_days=impulse.cross_lookback_days + 1, require_positive_impulse=False,
                    require_close_above_ma20=False, require_ma20_above_ma60=False, require_ma20_rising=False)
    result = scan_impulse_universe(universe, histories, broad, download_errors)
    records = [describe_event(event, result["details"][event["ticker"]], revenue, strong, asof)
               for event in result["events"].to_dict("records")]
    result["events"] = pd.DataFrame(records)
    result["candidates"] = rank_strong(result["events"])
    result["stats"]["strong_candidates"] = len(result["candidates"])
    return result
