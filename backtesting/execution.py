"""Sequential long-only daily execution. No detector or network dependencies."""
import math
import numpy as np
import pandas as pd


def stop_price(entry, signal, config):
    if config.stop_method == "FLAG_LOW":
        stop = signal["flag_swing_low"]
    elif config.stop_method == "ATR":
        stop = entry - signal["signal_atr"] * config.atr_multiplier
    else:
        stop = entry * (1 - config.stop_pct)
    if not math.isfinite(stop) or not 0 < stop < entry:
        raise ValueError("Invalid stop/risk at next open")
    return float(stop)


def valid_bar(bar):
    values = [bar.get(k, np.nan) for k in ("Open", "High", "Low", "Close", "Volume")]
    return (all(math.isfinite(v) and v > 0 for v in values)
            and bar.Low <= min(bar.Open, bar.Close) <= max(bar.Open, bar.Close) <= bar.High)


def calculate_pnl(entry, exit_price, quantity, risk, costs):
    slip = costs.slippage if costs.enabled else 0
    entry_fill, exit_fill = entry * (1 + slip), exit_price * (1 - slip)
    buy_value, sell_value = entry_fill * quantity, exit_fill * quantity
    entry_fee = max(costs.minimum_brokerage, buy_value * costs.brokerage_rate) if costs.enabled else 0
    exit_fee = max(costs.minimum_brokerage, sell_value * costs.brokerage_rate) if costs.enabled else 0
    tax = sell_value * costs.transaction_tax if costs.enabled else 0
    gross = (exit_price - entry) * quantity
    net = sell_value - buy_value - entry_fee - exit_fee - tax
    return dict(entry_fill_price=entry_fill, exit_fill_price=exit_fill,
                entry_fee=entry_fee, exit_fee=exit_fee, transaction_tax=tax,
                slippage_cost=gross - (sell_value - buy_value), gross_pnl=gross, net_pnl=net,
                gross_return_pct=gross / (entry * quantity), net_return_pct=net / (entry * quantity),
                gross_R=gross / (risk * quantity), result_R=net / (risk * quantity))


def simulate_trade(data, signal, rr, horizon, config):
    entry_pos = int(signal["signal_index"]) + 1
    if entry_pos >= len(data):
        return None, "No next trading-day open"
    first = data.iloc[entry_pos]
    if not valid_bar(first):
        return None, "Invalid entry OHLCV"
    entry = float(first.Open)
    try:
        stop = stop_price(entry, signal, config)
    except ValueError as error:
        return None, str(error)
    risk = entry - stop
    quantity = (int(config.starting_capital * config.risk_per_trade / risk)
                if config.sizing_mode == "FIXED_RISK" else int(config.position_shares))
    if quantity < 1:
        return None, "Position size below one share"
    target = entry + rr * risk
    record = dict(signal, entry_date=data.index[entry_pos], entry_price=entry,
                  stop_method=config.stop_method, stop_price=stop, risk_per_share=risk,
                  quantity=quantity, RR_target=rr, target_price=target, max_holding_days=horizon,
                  same_bar_ambiguous=False, outcome="CENSORED", exit_price=np.nan,
                  exit_date=pd.NaT, exit_reason="End of available data", holding_days=0,
                  excursion_basis="Daily-bar bounds including exit candle; not intraday path")
    max_high, min_low = entry, entry
    for pos in range(entry_pos, min(len(data), entry_pos + horizon)):
        bar = data.iloc[pos]
        record.update(exit_date=data.index[pos], exit_index=pos, holding_days=pos - entry_pos + 1)
        if not valid_bar(bar):
            record["exit_reason"] = "Missing/invalid bar during holding period"
            break
        # Opening auction comes before the intraday extremes. Gap exits use open.
        gap_stop, gap_target = bar.Open <= stop, bar.Open >= target
        if gap_stop or gap_target:
            max_high, min_low = max(max_high, bar.Open), min(min_low, bar.Open)
            record.update(outcome="LOSS" if gap_stop else "WIN", exit_price=float(bar.Open), exit_reason="Opening gap")
            break
        max_high, min_low = max(max_high, bar.High), min(min_low, bar.Low)
        hit_stop, hit_target = bar.Low <= stop, bar.High >= target
        if hit_stop and hit_target:
            record["same_bar_ambiguous"] = True
            if config.same_bar_policy == "EXCLUDE":
                record.update(outcome="AMBIGUOUS", exit_reason="Both levels touched; excluded")
                break
            hit_target = config.same_bar_policy == "OPTIMISTIC"
            hit_stop = not hit_target
        if hit_stop or hit_target:
            record.update(outcome="LOSS" if hit_stop else "WIN", exit_price=stop if hit_stop else target,
                          exit_reason="Stop/target touch")
            break
        if pos - entry_pos + 1 == horizon:
            record.update(outcome="TIMEOUT", exit_price=float(bar.Close), exit_reason="Holding limit close")
    record.update(MFE_pct=float(max_high / entry - 1), MFE_R=float((max_high - entry) / risk),
                  MAE_pct=float(min_low / entry - 1), MAE_R=float((min_low - entry) / risk))
    if record["outcome"] in ("WIN", "LOSS", "TIMEOUT"):
        record.update(calculate_pnl(entry, record["exit_price"], quantity, risk, config.costs))
    else:
        for key in ("entry_fill_price", "exit_fill_price", "entry_fee", "exit_fee", "transaction_tax",
                    "slippage_cost", "gross_pnl", "net_pnl", "gross_return_pct", "net_return_pct", "gross_R", "result_R"):
            record[key] = np.nan
    return record, None
