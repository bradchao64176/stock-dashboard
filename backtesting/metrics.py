"""Realized net-R research metrics; no claim of a capital-constrained portfolio."""
import numpy as np
import pandas as pd

COMPLETED = ("WIN", "LOSS", "TIMEOUT")


def equity_curve(trades, starting_capital=1000000):
    columns = ["date", "cumulative_R", "equity", "drawdown_pct"]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    realized = trades[trades.outcome.isin(COMPLETED)].sort_values(["exit_date", "ticker", "signal_date"])
    if realized.empty:
        return pd.DataFrame(columns=columns)
    daily = realized.groupby("exit_date")[["result_R", "net_pnl"]].sum().sort_index()
    baseline_date = pd.Timestamp(trades.entry_date.min()) - pd.Timedelta(days=1)
    baseline = pd.DataFrame({"result_R": [0.0], "net_pnl": [0.0]}, index=[baseline_date])
    daily = pd.concat([baseline, daily])
    equity = starting_capital + daily.net_pnl.cumsum()
    peak = equity.cummax()
    return pd.DataFrame(dict(date=daily.index, cumulative_R=daily.result_R.cumsum().values,
                             equity=equity.values, drawdown_pct=(equity / peak - 1).values))


def longest_streak(outcomes, value):
    longest = current = 0
    for outcome in outcomes:
        current = current + 1 if outcome == value else 0
        longest = max(longest, current)
    return longest


def summarize(trades, rr, total_signals=0, starting_capital=1000000):
    base = dict(total_signals=total_signals, total_trades=len(trades), evaluated_trades=0,
                wins=0, losses=0, timeouts=0, ambiguous_trades=0, excluded_ambiguous=0, censored=0,
                win_rate=np.nan, loss_rate=np.nan, timeout_rate=np.nan, decided_win_rate=np.nan,
                break_even_win_rate=1 / (1 + rr), average_R=np.nan, median_R=np.nan,
                expectancy=np.nan, profit_factor=np.nan, average_return=np.nan, median_return=np.nan,
                average_holding_days=np.nan, maximum_drawdown=np.nan, consecutive_wins=0,
                consecutive_losses=0, MFE_R=np.nan, MAE_R=np.nan, hit_rate_all_entries=np.nan)
    if trades.empty:
        return base
    base.update(wins=int((trades.outcome == "WIN").sum()), losses=int((trades.outcome == "LOSS").sum()),
                timeouts=int((trades.outcome == "TIMEOUT").sum()),
                ambiguous_trades=int(trades.same_bar_ambiguous.sum()),
                excluded_ambiguous=int((trades.outcome == "AMBIGUOUS").sum()),
                censored=int((trades.outcome == "CENSORED").sum()))
    base["hit_rate_all_entries"] = base["wins"] / len(trades)
    eligible = trades[trades.outcome.isin(COMPLETED)].sort_values(["exit_date", "ticker", "signal_date"])
    n = len(eligible)
    base["evaluated_trades"] = n
    if not n:
        return base
    r = eligible.result_R
    positive, negative = r[r > 0].sum(), -r[r < 0].sum()
    curve = equity_curve(trades, starting_capital)
    base.update(win_rate=base["wins"] / n, loss_rate=base["losses"] / n, timeout_rate=base["timeouts"] / n,
                decided_win_rate=(base["wins"] / (base["wins"] + base["losses"])
                                  if base["wins"] + base["losses"] else np.nan),
                average_R=float(r.mean()), median_R=float(r.median()), expectancy=float(r.mean()),
                profit_factor=float(positive / negative) if negative else (np.inf if positive else np.nan),
                average_return=float(eligible.net_return_pct.mean()), median_return=float(eligible.net_return_pct.median()),
                average_holding_days=float(eligible.holding_days.mean()),
                maximum_drawdown=float(-curve.drawdown_pct.min()),
                consecutive_wins=longest_streak(eligible.outcome, "WIN"),
                consecutive_losses=longest_streak(eligible.outcome, "LOSS"),
                MFE_R=float(eligible.MFE_R.mean()), MAE_R=float(eligible.MAE_R.mean()))
    return base


def comparison_table(trades, signals, config, samples=("ALL",)):
    records = []
    for sample in samples:
        sample_signals = signals[signals["sample"] == sample] if not signals.empty else signals
        for horizon in config.holding_periods:
            for rr in config.rr_targets:
                selected = trades[(trades["sample"] == sample) & (trades.RR_target == rr)
                                  & (trades.max_holding_days == horizon)] if not trades.empty else trades
                records.append(dict(sample=sample, RR_target=rr, max_holding_days=horizon,
                                    **summarize(selected, rr, len(sample_signals), config.starting_capital)))
    return pd.DataFrame(records)


def parameter_analysis(trades, dimension, rr, starting_capital):
    if trades.empty:
        return pd.DataFrame()
    groups = {
        "Bull Flag Score": ("bull_flag_score", [0, 60, 70, 80, 90, 101], ["<60", "60–69", "70–79", "80–89", "90–100"]),
        "Flagpole strength": ("flagpole_return_pct", [0, .2, .3, .5, np.inf], None),
        "Pullback depth": ("retracement", [0, .2, .35, .5, np.inf], None),
        "Volume contraction": ("volume_ratio", [0, .5, .75, 1, np.inf], None),
        "Breakout volume": ("breakout_volume_ratio", [0, 1.2, 1.5, 2, np.inf], None),
    }
    if dimension == "Market":
        labels = trades.market
    else:
        column, edges, names = groups[dimension]
        labels = pd.cut(trades[column], edges, labels=names, right=False)
    rows = []
    for label, group in trades.groupby(labels, observed=True):
        rows.append(dict(group=str(label), **summarize(group, rr, starting_capital=starting_capital)))
    return pd.DataFrame(rows)
