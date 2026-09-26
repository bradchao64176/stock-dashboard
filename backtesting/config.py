"""All execution and cost assumptions are explicit and serializable."""
from dataclasses import dataclass
import math

from src.bull_flag_config import BullFlagConfig


@dataclass(frozen=True)
class TradingCosts:
    enabled: bool = True
    brokerage_rate: float = 0.001425
    minimum_brokerage: float = 20.0
    transaction_tax: float = 0.003
    slippage: float = 0.0005

    def __post_init__(self):
        for value in (self.brokerage_rate, self.minimum_brokerage, self.transaction_tax, self.slippage):
            if not math.isfinite(value) or value < 0:
                raise ValueError("Costs must be finite and nonnegative")
        if max(self.brokerage_rate, self.transaction_tax, self.slippage) >= 1:
            raise ValueError("Rates must be fractions below 1")


@dataclass(frozen=True)
class BacktestConfig:
    detector: BullFlagConfig = BullFlagConfig()
    require_breakout_volume: bool = True
    require_volume_contraction: bool = False
    stop_method: str = "FLAG_LOW"
    atr_period: int = 14
    atr_multiplier: float = 1.5
    stop_pct: float = 0.05
    rr_targets: tuple = (1.0, 1.5, 2.0, 2.5, 3.0)
    holding_periods: tuple = (5, 10, 20, 30)
    same_bar_policy: str = "CONSERVATIVE"
    allow_overlap: bool = False
    costs: TradingCosts = TradingCosts()
    starting_capital: float = 1000000.0
    sizing_mode: str = "FIXED_RISK"
    risk_per_trade: float = 0.01
    position_shares: int = 1000

    def __post_init__(self):
        if self.stop_method not in ("FLAG_LOW", "ATR", "PERCENTAGE"):
            raise ValueError("Unknown stop method")
        if self.same_bar_policy not in ("CONSERVATIVE", "OPTIMISTIC", "EXCLUDE"):
            raise ValueError("Unknown same-bar policy")
        if self.sizing_mode not in ("FIXED_RISK", "FIXED_SHARES"):
            raise ValueError("Unknown sizing mode")
        values = (self.atr_multiplier, self.starting_capital, self.risk_per_trade, self.stop_pct)
        if any(not math.isfinite(x) or x <= 0 for x in values):
            raise ValueError("Risk parameters must be positive and finite")
        if not (self.atr_period >= 1 and self.position_shares >= 1
                and self.risk_per_trade < 1 and self.stop_pct < 1):
            raise ValueError("Invalid risk settings")
        if not self.rr_targets or any(not math.isfinite(r) or r <= 0 for r in self.rr_targets):
            raise ValueError("RR targets must be positive")
        if not self.holding_periods or any(int(h) != h or h < 1 for h in self.holding_periods):
            raise ValueError("Holding periods must be positive integers")
        if len(set(self.rr_targets)) != len(self.rr_targets) or len(set(self.holding_periods)) != len(self.holding_periods):
            raise ValueError("Duplicate scenarios")
