"""Gap strategy settings, independent of the original scanner and backtest."""
from dataclasses import dataclass
import math

from src.bull_flag_config import BullFlagConfig


@dataclass(frozen=True)
class GapScoreWeights:
    bull_flag: float = 25
    breakout: float = 20
    gap_size: float = 15
    volume: float = 15
    preservation: float = 15
    current_trend: float = 10


@dataclass(frozen=True)
class GapConfig:
    detector: BullFlagConfig = BullFlagConfig()
    gap_lookback_days: int = 20
    gap_definition: str = "FULL_GAP"
    min_gap_pct: float = .01
    gap_breakout_window: int = 0
    require_gap_volume_confirmation: bool = True
    min_breakout_volume_ratio: float = 1.2
    min_gap_breakout_score: float = 0
    only_untouched_gaps: bool = False
    full_breakout_strength: float = .05
    full_gap_size: float = .05
    full_volume_ratio: float = 3
    full_trend_spread: float = .10
    adjustment_change_tolerance: float = .001
    max_unexplained_daily_change: float = .30
    weights: GapScoreWeights = GapScoreWeights()

    def __post_init__(self):
        if self.gap_definition not in ("FULL_GAP", "OPEN_GAP"):
            raise ValueError("Gap definition must be FULL_GAP or OPEN_GAP")
        if not (1 <= self.gap_lookback_days <= 252 and 0 <= self.gap_breakout_window <= 2):
            raise ValueError("Invalid gap lookback/window")
        if not (0 <= self.min_gap_pct < 1 and 0 <= self.min_gap_breakout_score <= 100):
            raise ValueError("Invalid gap/score threshold")
        values = (self.min_gap_pct, self.min_breakout_volume_ratio, self.min_gap_breakout_score,
                  self.full_breakout_strength, self.full_gap_size, self.full_volume_ratio,
                  self.full_trend_spread, self.adjustment_change_tolerance, self.max_unexplained_daily_change)
        if any(not math.isfinite(x) or x < 0 for x in values):
            raise ValueError("Thresholds must be finite and nonnegative")
        if min(self.full_breakout_strength, self.full_gap_size, self.full_volume_ratio,
               self.full_trend_spread) <= 0:
            raise ValueError("Score denominators must be positive")
        weights = list(vars(self.weights).values())
        if any(not math.isfinite(x) or x < 0 for x in weights) or abs(sum(weights) - 100) > 1e-8:
            raise ValueError("Gap score weights must total 100")
