from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SMCConfig:
    timeframe: str = "Daily"
    swing_left: int = 5
    swing_right: int = 5
    internal_left: int = 3
    internal_right: int = 3
    lookback: int = 60
    volume_period: int = 20
    min_volume_ratio: float = 1.5
    min_traded_value: float = 100_000_000
    breakout_buffer: float = .005
    direction: str = "BULLISH"
    structure_type: str = "SWING"
    weekly_filter: bool = False
    macd_confirmation: bool = False
    macd_age: int = 3
    bos_confirmation: bool = False
    ob_retest: bool = False
    entry_mode: str = "BREAKOUT"
    stop_buffer: float = .005
    target_r: float = 2.
    signal_age: int = 10
    ob_lookback: int = 10

    def __post_init__(self):
        for key in ("swing_left", "swing_right", "internal_left", "internal_right", "lookback",
                    "volume_period", "macd_age", "signal_age", "ob_lookback"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        for key in ("min_volume_ratio", "min_traded_value", "breakout_buffer", "stop_buffer", "target_r"):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) < 0:
                raise ValueError(f"Invalid {key}")
        if self.target_r <= 0 or max(self.breakout_buffer, self.stop_buffer) >= 1:
            raise ValueError("Invalid risk/buffer")
        if self.timeframe not in ("Daily", "Weekly") or self.direction not in ("BULLISH", "BEARISH"):
            raise ValueError("Invalid timeframe/direction")
        if self.structure_type not in ("SWING", "INTERNAL"):
            raise ValueError("Invalid structure type")
        if self.entry_mode not in ("BREAKOUT", "RETEST", "ORDER_BLOCK", "BOS"):
            raise ValueError("Invalid entry mode")
