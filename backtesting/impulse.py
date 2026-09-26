"""A–F Impulse experiments through the existing execution and metrics engine."""
from dataclasses import replace

import numpy as np
import pandas as pd

from backtesting.config import BacktestConfig
from backtesting.engine import execute_backtest
from src.bull_flag_gap import normalize_dates, observed_sessions
from src.impulse_macd import ImpulseConfig, calculate_impulse, historical_cross_events
from src.strong_impulse import StrongConfig, describe_event

VARIANTS = {
    "A_PURE": [],
    "B_ABOVE_ZERO": ["above_zero"],
    "C_TREND": ["above_zero", "close_above_ma20", "ma20_above_ma60"],
    "D_RISING": ["above_zero", "close_above_ma20", "ma20_above_ma60", "ma20_rising"],
    "E_VOLUME": ["above_zero", "close_above_ma20", "ma20_above_ma60", "ma20_rising", "volume_expansion"],
    "F_REVENUE": ["above_zero", "close_above_ma20", "ma20_above_ma60", "ma20_rising", "volume_expansion", "revenue_growth"],
}


def compare_impulse_variants(universe, histories, revenue, impulse=ImpulseConfig(), strong=StrongConfig(),
                             execution=BacktestConfig(stop_method="ATR")):
    if execution.stop_method == "FLAG_LOW":
        raise ValueError("Impulse has no flag swing low; select ATR or percentage stop")
    prepared, records, issues = {}, [], []
    calendar = observed_sessions(histories)
    broad = replace(impulse, require_positive_impulse=False, require_close_above_ma20=False,
                    require_ma20_above_ma60=False, require_ma20_rising=False)
    for stock in universe.to_dict("records"):
        try:
            raw = normalize_dates(histories[stock["ticker"]])
            data = calculate_impulse(raw.reindex(calendar[calendar >= raw.index.min()]), broad)
            # ATR uses only contiguous valid bars and the chosen execution period.
            for _, segment in data[data.valid_bar].groupby((~data.valid_bar).cumsum()[data.valid_bar]):
                previous = segment.Close.shift(1)
                tr = pd.concat([segment.High - segment.Low, (segment.High - previous).abs(), (segment.Low - previous).abs()], axis=1).max(axis=1)
                data.loc[segment.index, "ATR"] = tr.rolling(execution.atr_period).mean()
            prepared[stock["ticker"]] = data
            for event in historical_cross_events(data, stock, broad):
                pos = event["signal_index"]
                detail = describe_event(event, data, revenue, strong, event["signal_date"] + pd.Timedelta(hours=14), current_pos=pos)
                detail["signal_atr"] = float(data.ATR.iloc[pos])
                records.append(detail)
        except Exception as error:
            issues.append(dict(ticker=stock["ticker"], reason=str(error)))
    all_signals = pd.DataFrame(records)
    comparisons, trades, forwards, selected_signals = [], [], [], []
    for variant, rules in VARIANTS.items():
        signals = all_signals.copy()
        for rule in rules:
            if not signals.empty:
                signals = signals[signals["condition_" + rule]]
        if strong.require_positive_cross_day_return and variant in ("E_VOLUME", "F_REVENUE") and not signals.empty:
            signals = signals[signals.condition_positive_cross_day_return]
        signals = signals.copy()
        signals["variant"] = variant
        signal_set = dict(signals=signals, histories=prepared, issues=issues,
                          stats=dict(total_stocks=len(universe), stocks_analyzed=len(prepared), signals=len(signals)))
        run = execute_backtest(signal_set, execution)
        run["comparison"]["variant"] = variant
        run["comparison"]["revenue_coverage_signals"] = int((all_signals.revenue_status == "AVAILABLE").sum()) if not all_signals.empty else 0
        comparisons.append(run["comparison"])
        if not run["trades"].empty:
            trades.append(run["trades"])
        selected_signals.append(signals)
        for event in signals.to_dict("records"):
            data = prepared[event["ticker"]]
            entry = event["signal_index"] + 1
            row = dict(variant=variant, signal_id=event["signal_id"], ticker=event["ticker"], signal_date=event["signal_date"])
            for days in (5, 10, 20, 30):
                last = entry + days - 1
                eligible = last < len(data) and data.valid_bar.iloc[entry:last + 1].all()
                row[f"return_{days}d"] = float(data.Close.iloc[last] / data.Open.iloc[entry] - 1) if eligible else np.nan
            forwards.append(row)
    forward = pd.DataFrame(forwards)
    summary = pd.concat(comparisons, ignore_index=True)
    if not forward.empty:
        for days in (5, 10, 20, 30):
            grouped = forward.groupby("variant")[f"return_{days}d"]
            summary[f"average_{days}d_return"] = summary.variant.map(grouped.mean())
            summary[f"count_{days}d_return"] = summary.variant.map(grouped.count()).fillna(0)
    return dict(comparison=summary, trades=pd.concat(trades, ignore_index=True) if trades else pd.DataFrame(),
                signals=pd.concat(selected_signals, ignore_index=True), all_signals=all_signals,
                forward_returns=forward, issues=pd.DataFrame(issues))
