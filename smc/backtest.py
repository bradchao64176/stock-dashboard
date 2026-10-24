"""Independent chronological comparison, next daily open, no existing engine changes."""
import math
import pandas as pd
from backtesting.config import TradingCosts
from backtesting.execution import calculate_pnl
from src.impulse_macd import calculate_impulse, ImpulseConfig
from .data import prepare_daily
from .timeframes import weekly_bars, volume_ratios
from .market_structure import analyze_structure
from .bos_detector import subsequent_bos


def execute(daily, event, target_r=2., horizon=20, shares=1000, costs=TradingCosts()):
    available = daily.index[daily.index > pd.Timestamp(event.get("confirmed_at",event["signal_date"])).normalize()]
    if available.empty:
        return None
    entry_pos = daily.index.get_loc(available[0])
    if not daily.valid_bar.iloc[entry_pos]:
        return None
    entry = float(daily.Open.iloc[entry_pos]); stop = event["stop"]
    sign = 1 if event["direction"] == "BULLISH" else -1
    risk = sign*(entry-stop)
    if not math.isfinite(risk) or risk <= 0 or stop <= 0:
        return None
    target = entry + sign*target_r*risk
    if target <= 0:
        return None
    for i in range(entry_pos, min(len(daily),entry_pos+horizon)):
        bar = daily.iloc[i]
        if not bar.valid_bar:
            return None  # Censored discontinuity, not a fictitious executable return.
        if sign*(bar.Open-stop) <= 0:
            exit_price, reason = float(bar.Open), "GAP_STOP"
        elif sign*(bar.Open-target) >= 0:
            exit_price, reason = float(bar.Open), "GAP_TARGET"
        elif (bar.Low <= stop if sign==1 else bar.High >= stop):
            exit_price, reason = stop, "STOP"  # Conservative if both levels touched.
        elif (bar.High >= target if sign==1 else bar.Low <= target):
            exit_price, reason = target, "TARGET"
        elif i == entry_pos+horizon-1:
            exit_price, reason = float(bar.Close), "TIMEOUT"
        else:
            continue
        if sign == 1:
            accounting = calculate_pnl(entry,exit_price,shares,risk,costs)
            pnl, ret = accounting["net_pnl"], accounting["net_return_pct"]
        else:
            slip = costs.slippage if costs.enabled else 0
            sell, buy = entry*(1-slip)*shares, exit_price*(1+slip)*shares
            fees = ((max(costs.minimum_brokerage,sell*costs.brokerage_rate)+max(costs.minimum_brokerage,buy*costs.brokerage_rate)
                     +sell*costs.transaction_tax) if costs.enabled else 0)
            pnl = sell-buy-fees; ret = pnl/(entry*shares)
        return dict(event,entry_date=daily.index[entry_pos],exit_date=daily.index[i],entry_price=entry,
                    exit_price=exit_price,target=target,net_pnl=pnl,net_return=ret,
                    holding_days=i-entry_pos+1,exit_reason=reason)
    return None


def summarize(trades, labels):
    rows = []
    for label in labels:
        frame = trades.loc[trades.strategy.eq(label)].sort_values(["exit_date","ticker"]) if not trades.empty else pd.DataFrame()
        if frame.empty:
            rows.append(dict(strategy=label,total_trades=0,win_rate=None,average_return=None,max_drawdown=None,
                             profit_factor=None,average_holding_days=None))
            continue
        pnl = frame.groupby("exit_date").net_pnl.sum()
        equity = 1_000_000+pnl.cumsum()
        peak = equity.cummax().clip(lower=1_000_000)
        wins, losses = frame.loc[frame.net_pnl>0,"net_pnl"].sum(), -frame.loc[frame.net_pnl<0,"net_pnl"].sum()
        rows.append(dict(strategy=label,total_trades=len(frame),win_rate=float((frame.net_pnl>0).mean()),
                         average_return=float(frame.net_return.mean()),max_drawdown=float((equity/peak-1).min()),
                         profit_factor=float(wins/losses) if losses else None,
                         average_holding_days=float(frame.holding_days.mean())))
    return pd.DataFrame(rows)


def compare(universe, histories, config, calendar, asof, costs=TradingCosts(), progress=None):
    labels = ["Original Pure Impulse MACD (long)", "CHOCH", "CHOCH + MACD", "CHOCH followed by BOS"]
    trades, errors = [], {}
    for number, stock in enumerate(universe.to_dict("records"), 1):
        if progress:
            progress(number, len(universe))
        ticker = stock["ticker"]
        if ticker not in histories:
            errors[ticker] = "Missing history"; continue
        try:
            daily = prepare_daily(histories[ticker],asof,calendar)
            data = weekly_bars(daily,asof,calendar) if config.timeframe=="Weekly" else daily
            if data.empty:
                continue
            source = data.copy(); source.loc[~source.valid_bar,["Open","High","Low","Close","Volume"]] = float("nan")
            indicators = calculate_impulse(source,ImpulseConfig())
            structure = analyze_structure(data,ticker,config,config.structure_type)
            volumes = data.Volume/volume_ratios(data,config.volume_period)
            candidate_sets = {label:[] for label in labels}
            for i in range(len(data)):
                # Existing Pure Impulse formula, with a common causal structural stop for comparison.
                if bool(indicators.golden_cross.iloc[i]) and i >= 10:
                    stop = float(data.Low.iloc[i-10:i].min())*(1-config.stop_buffer)
                    candidate_sets[labels[0]].append(dict(signal_date=data.index[i],confirmed_at=data.available_at.iloc[i],stop=stop,direction="BULLISH"))
            for event in structure["events"]:
                if event["kind"] != "CHOCH" or event["direction"] != config.direction or event["invalidation_level"] is None:
                    continue
                i = event["position"]
                if pd.isna(volumes.iloc[i]) or volumes.iloc[i]<config.min_volume_ratio or data.trading_value.iloc[i]<config.min_traded_value:
                    continue
                sign = 1 if event["direction"]=="BULLISH" else -1
                base = dict(signal_date=event["signal_date"],confirmed_at=event["confirmed_at"],stop=event["invalidation_level"]*(1-sign*config.stop_buffer),direction=event["direction"])
                candidate_sets[labels[1]].append(base)
                md, sig = indicators.Impulse_MACD, indicators.Impulse_Signal
                crossed = (sign*(md-sig)>0) & (sign*(md.shift(1)-sig.shift(1))<=0)
                if sign*(md.iloc[i]-sig.iloc[i])>0 and crossed.iloc[max(0,i-config.macd_age+1):i+1].any():
                    candidate_sets[labels[2]].append(base)
                bos = subsequent_bos(structure,event)
                if bos:
                    prefix = data.iloc[i:bos["position"]+1]
                    held = (prefix.Low>base["stop"]).all() if sign==1 else (prefix.High<base["stop"]).all()
                    if prefix.valid_bar.all() and held:
                        candidate_sets[labels[3]].append(dict(base,signal_date=bos["signal_date"],confirmed_at=bos["confirmed_at"]))
            for label, events in candidate_sets.items():
                last_exit = None
                for event in sorted(events,key=lambda e:e["signal_date"]):
                    if last_exit is not None and event["signal_date"]<=last_exit:
                        continue
                    trade = execute(daily,dict(event,ticker=ticker,strategy=label),config.target_r,costs=costs)
                    if trade:
                        trades.append(trade); last_exit=trade["exit_date"]
        except (ValueError,KeyError,TypeError) as error:
            errors[ticker]=str(error)
    frame = pd.DataFrame(trades)
    return dict(summary=summarize(frame,labels),trades=frame,errors=errors,
                assumptions="1000 shares; next daily open; 20 daily-session limit; realized equity on TWD 1M; no cross-stock capital cap; shorts hypothetical without borrow availability/cost; raw prices; action discontinuities censored; current universe survivorship and data-revision bias.")
