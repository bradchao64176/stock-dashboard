"""Independent unfilled-gap trend strategy; does not require a Bull Flag."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TrendConfig:
    require_close_above_ma20: bool = True
    require_ma20_above_ma60: bool = True
    require_ma20_rising: bool = True
    require_ma60_rising: bool = False
    require_full_ma_alignment: bool = False
    ma_slope_lookback: int = 5
    trend_evaluation: str = "GAP_DAY_AND_CURRENT"
    enable_distance_filter: bool = False
    min_ma20_ma60_distance_pct: float = 0.0
    max_ma20_ma60_distance_pct: object = None

    def __post_init__(self):
        if not 1 <= self.ma_slope_lookback <= 60:
            raise ValueError("MA slope lookback must be 1–60 sessions")
        if self.trend_evaluation not in ("GAP_DAY", "CURRENT", "GAP_DAY_AND_CURRENT"):
            raise ValueError("Unknown trend evaluation mode")
        low, high = self.min_ma20_ma60_distance_pct, self.max_ma20_ma60_distance_pct
        if not math.isfinite(low) or (high is not None and (not math.isfinite(high) or high < low)):
            raise ValueError("Invalid MA distance bounds")


@dataclass(frozen=True)
class UnfilledScoreWeights:
    trend_quality: float = 20
    recent_return: float = 20
    gap_size: float = 15
    preservation: float = 20
    post_gap_strength: float = 10
    gap_volume: float = 15


@dataclass(frozen=True)
class UnfilledGapConfig:
    trend: TrendConfig = TrendConfig()
    gap_lookback_days: int = 20
    return_lookback_days: int = 20
    min_return_pct: float = .10
    gap_definition: str = "FULL_GAP"
    min_gap_pct: float = .01
    only_untouched_gaps: bool = False
    require_volume_confirmation: bool = False
    min_volume_ratio: float = 1.2
    min_score: float = 0
    weights: UnfilledScoreWeights = UnfilledScoreWeights()
    full_return: float = .30
    full_gap_size: float = .05
    full_post_gap_strength: float = .10
    full_volume_ratio: float = 3
    full_ma20_slope: float = .02
    full_ma60_slope: float = .01
    full_ma_distance: float = .10
    adjustment_change_tolerance: float = .001
    max_unexplained_daily_change: float = .30

    def __post_init__(self):
        if not (1 <= self.gap_lookback_days <= 252 and 1 <= self.return_lookback_days <= 120):
            raise ValueError("Invalid gap/return lookback")
        if self.gap_definition not in ("FULL_GAP", "OPEN_GAP"):
            raise ValueError("Invalid gap definition")
        if not (math.isfinite(self.min_return_pct) and -.99 <= self.min_return_pct
                and 0 <= self.min_gap_pct < 1 and 0 <= self.min_score <= 100
                and math.isfinite(self.min_volume_ratio) and self.min_volume_ratio >= 0):
            raise ValueError("Invalid filters")
        denominators = (self.full_return, self.full_gap_size, self.full_post_gap_strength,
                        self.full_volume_ratio, self.full_ma20_slope, self.full_ma60_slope, self.full_ma_distance)
        if any(not math.isfinite(x) or x <= 0 for x in denominators):
            raise ValueError("Score denominators must be finite and positive")
        weights = list(vars(self.weights).values())
        if any(not math.isfinite(w) or w < 0 for w in weights) or abs(sum(weights) - 100) > 1e-8:
            raise ValueError("Score weights must total 100")
