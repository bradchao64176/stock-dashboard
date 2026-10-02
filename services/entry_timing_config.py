"""Entry-only settings; percentage thresholds are fractions (0.03 = 3%)."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class EntryTimingConfig:
    pullback_low_pct: float = 0.0
    pullback_high_pct: float = 0.03
    watch_max_distance_pct: float = 0.07
    extended_max_distance_pct: float = 0.12
    breakout_buffer_pct: float = 0.01
    cross_entry_buffer_pct: float = 0.01
    breakout_volume_ratio: float = 1.5
    max_cross_entry_age_days: int = 3
    resistance_lookback: int = 20
    atr_period: int = 14
    atr_stop_multiplier: float = 0.5
    swing_lookback: int = 10
    stop_mode: str = "STRUCTURAL"
    require_volume_contraction: bool = False
    require_expanding_breakout: bool = True

    def __post_init__(self):
        for key in ("pullback_low_pct", "pullback_high_pct", "watch_max_distance_pct",
                    "extended_max_distance_pct", "breakout_buffer_pct", "cross_entry_buffer_pct",
                    "breakout_volume_ratio", "atr_stop_multiplier"):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) < 0:
                raise ValueError(f"Invalid {key}")
        if not (self.pullback_low_pct <= self.pullback_high_pct <= self.watch_max_distance_pct
                <= self.extended_max_distance_pct):
            raise ValueError("Entry distance thresholds must be ordered")
        for key in ("resistance_lookback", "atr_period", "swing_lookback", "max_cross_entry_age_days"):
            value = getattr(self, key)
            if type(value) is not int or value < (0 if key == "max_cross_entry_age_days" else 1):
                raise ValueError(f"Invalid {key}")
        if self.stop_mode not in ("STRUCTURAL", "MA20_ATR"):
            raise ValueError("Unknown stop mode")
