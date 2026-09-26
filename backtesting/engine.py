"""Orchestrate independent RR/horizon scenarios from shared historical signals."""
from datetime import datetime, timezone
import pandas as pd

from backtesting.config import BacktestConfig
from backtesting.execution import simulate_trade
from backtesting.metrics import comparison_table
from backtesting.signals import generate_signals, prepare_history


def build_signal_set(universe, histories, config=BacktestConfig(), signal_start=None, signal_end=None, progress=None):
    records, issues, prepared = [], [], {}
    stocks = universe.drop_duplicates("ticker").to_dict("records")
    for count, stock in enumerate(stocks, 1):
        ticker = stock["ticker"]
        try:
            data = prepare_history(histories.get(ticker), config)
            invalid = int((~data.valid_bar).sum())
            if invalid:
                issues.append(dict(ticker=ticker, stage="validation", reason=f"{invalid} invalid bars; warmup resets"))
            stock_records = generate_signals(data, stock, config, signal_start, signal_end)
            prepared[ticker] = data
            records.extend(stock_records)
        except Exception as error:
            issues.append(dict(ticker=ticker, stage="signals", reason=str(error)))
        if progress:
            progress(count, len(stocks))
    return dict(signals=pd.DataFrame(records), histories=prepared, issues=issues,
                stats=dict(total_stocks=len(stocks), stocks_analyzed=len(prepared), signals=len(records)))


def execute_backtest(signal_set, config=BacktestConfig(), split_date=None, evaluation_end=None):
    """Optional fixed date split; training positions never use test-period bars.

    Parameters are supplied, not optimized. Each RR/horizon has an independent
    position ledger; a previous close-time exit allows entry at the next open.
    """
    signals = signal_set["signals"].copy()
    samples = ("TRAIN", "OOS") if split_date is not None else ("ALL",)
    if not signals.empty:
        signals["sample"] = "ALL"
        if split_date is not None:
            signals["sample"] = signals.signal_date.map(lambda d: "TRAIN" if d < pd.Timestamp(split_date) else "OOS")
    records, skipped = [], []
    for sample in samples:
        subset = signals[signals["sample"] == sample] if not signals.empty else signals
        if subset.empty:
            continue
        for ticker, stock_signals in subset.groupby("ticker"):
            data = signal_set["histories"][ticker]
            if evaluation_end is not None:
                data = data.loc[:pd.Timestamp(evaluation_end)]
            if sample == "TRAIN":
                data = data[data.index < pd.Timestamp(split_date)]
            for rr in config.rr_targets:
                for horizon in config.holding_periods:
                    busy_until = -1
                    for signal in stock_signals.sort_values("signal_date").to_dict("records"):
                        entry_pos = int(signal["signal_index"]) + 1
                        if not config.allow_overlap and entry_pos <= busy_until:
                            skipped.append(dict(signal_id=signal["signal_id"], ticker=ticker, sample=sample,
                                                RR_target=rr, max_holding_days=horizon, reason="Overlapping position"))
                            continue
                        trade, error = simulate_trade(data, signal, rr, horizon, config)
                        if trade is None:
                            skipped.append(dict(signal_id=signal["signal_id"], ticker=ticker, sample=sample,
                                                RR_target=rr, max_holding_days=horizon, reason=error))
                            continue
                        records.append(trade)
                        # Unknown exit after a data defect conservatively blocks the rest
                        # of the nominal holding window rather than opening a new position.
                        busy_until = (entry_pos + horizon - 1 if trade["outcome"] == "CENSORED"
                                      else trade["exit_index"])
    trades = pd.DataFrame(records)
    comparison = comparison_table(trades, signals, config, samples)
    return dict(trades=trades, comparison=comparison, signals=signals,
                issues=signal_set["issues"], skipped=pd.DataFrame(skipped), stats=signal_set["stats"],
                config=config, split_date=split_date, evaluation_end=evaluation_end,
                generated_at=datetime.now(timezone.utc).isoformat())


def run_backtest(universe, histories, config=BacktestConfig(), signal_start=None,
                 signal_end=None, split_date=None, progress=None):
    signal_set = build_signal_set(universe, histories, config, signal_start, signal_end, progress)
    return execute_backtest(signal_set, config, split_date, signal_end)
