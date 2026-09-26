"""Immutable scanner settings; returns/retracements are fractions, not percent points."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreWeights:
    uptrend: float = 20
    flagpole: float = 20
    descending_flag: float = 20
    pullback: float = 15
    volume: float = 15
    breakout: float = 10


@dataclass(frozen=True)
class BullFlagConfig:
    min_history_days: int = 120
    flagpole_days: int = 20
    min_flagpole_return: float = 0.15
    min_flag_days: int = 5
    max_flag_days: int = 15
    max_retracement: float = 0.50
    slope_tolerance: float = 0.60
    min_regression_r2: float = 0.35
    breakout_volume_multiplier: float = 1.20
    min_bull_flag_score: float = 60
    full_trend_spread: float = 0.10
    full_flagpole_return: float = 0.30
    full_volume_contraction: float = 0.50
    weights: ScoreWeights = ScoreWeights()

    def __post_init__(self):
        if not (self.min_history_days >= 60 and self.flagpole_days >= 2
                and 3 <= self.min_flag_days <= self.max_flag_days):
            raise ValueError("Invalid history, flagpole or flag length")
        if not (0 < self.max_retracement <= 1 and self.min_flagpole_return > 0
                and self.slope_tolerance > 0 and 0 <= self.min_regression_r2 <= 1
                and self.breakout_volume_multiplier > 0
                and 0 <= self.min_bull_flag_score <= 100
                and self.full_trend_spread > 0 and self.full_flagpole_return > 0
                and 0 < self.full_volume_contraction < 1):
            raise ValueError("Invalid scanner thresholds")
        weights = vars(self.weights).values()
        if any(w < 0 for w in weights) or abs(sum(weights) - 100) > 1e-8:
            raise ValueError("Score weights must be nonnegative and total 100")
