"""Independent CHOCH selection; does not invoke any existing scanner."""
import pandas as pd
from src.impulse_macd import calculate_impulse, ImpulseConfig
from .data import prepare_daily, completed_cutoff
from .timeframes import weekly_bars, volume_ratios
from .market_structure import analyze_structure
from .choch_detector import choch_events
from .entry_analysis import analyze_entry


def analyze_stock(history, ticker, name, config, calendar, asof):
    daily = prepare_daily(history, asof, calendar)
    data = weekly_bars(daily, asof, calendar) if config.timeframe == "Weekly" else daily
    if len(data) < max(config.volume_period+1, config.swing_left+config.swing_right+2):
        raise ValueError("Insufficient completed candles")
    data = data.copy()
    data["volume_average"] = volume_ratios(data, config.volume_period)
    data["volume_ratio"] = data.Volume/data.volume_average
    structure = analyze_structure(data, ticker, config, config.structure_type)
    recent = [event for event in choch_events(structure) if event["direction"] == config.direction
              and len(data)-1-event["position"] < config.signal_age]
    if not recent:
        return [], {}
    other_type = "INTERNAL" if config.structure_type == "SWING" else "SWING"
    other = analyze_structure(data, ticker, config, other_type)
    # Read-only indicator reuse. Invalid corporate-action/missing bars stay invalid.
    indicator_input = data.copy()
    indicator_input.loc[~data.valid_bar, ["Open", "High", "Low", "Close", "Volume"]] = float("nan")
    indicators = calculate_impulse(indicator_input, ImpulseConfig())
    weekly_direction = None
    if config.weekly_filter:
        week = weekly_bars(daily, asof, calendar)
        if not week.empty:
            weekly_direction = analyze_structure(week, ticker, config, config.structure_type)["states"][-1]["structure"]
    cutoff = completed_cutoff(asof)
    sessions = calendar.sessions(cutoff-pd.Timedelta(days=30), cutoff)
    fresh = len(sessions) > 0 and daily.index[-1] == sessions[-1] and bool(data.valid_bar.iloc[-1])
    if config.timeframe == "Weekly":
        # The most recent completed week need not be the current calendar week.
        complete_weeks = []
        for period in pd.period_range(cutoff-pd.Timedelta(days=21), cutoff, freq="W-FRI"):
            expected = calendar.sessions(period.end_time.normalize()-pd.Timedelta(days=4), period.end_time.normalize())
            if len(expected) and period.end_time.normalize() <= cutoff:
                complete_weeks.append(expected[-1])
        fresh = bool(complete_weeks) and data.index[-1] == complete_weeks[-1] and bool(data.valid_bar.iloc[-1])
    rows = []
    for event in recent:
        if event["direction"] != config.direction or len(data)-1-event["position"] >= config.signal_age:
            continue
        bar = data.iloc[event["position"]]
        # Liquidity and volume are signal-time filters, never future values.
        if pd.isna(bar.volume_ratio) or bar.volume_ratio < config.min_volume_ratio or pd.isna(bar.trading_value) or bar.trading_value < config.min_traded_value:
            continue
        tail = indicators.iloc[-config.macd_age:]
        bullish = config.direction == "BULLISH"
        crosses = indicators.golden_cross if bullish else ((indicators.Impulse_MACD < indicators.Impulse_Signal) & (indicators.Impulse_MACD.shift(1) >= indicators.Impulse_Signal.shift(1)))
        now_macd, now_signal = indicators.Impulse_MACD.iloc[-1], indicators.Impulse_Signal.iloc[-1]
        macd_status = "BULLISH" if now_macd > now_signal else "BEARISH" if now_macd < now_signal else "NEUTRAL"
        macd_pass = bool(crosses.iloc[-len(tail):].any()) and macd_status == config.direction
        gates = (not config.macd_confirmation or macd_pass) and (not config.weekly_filter or weekly_direction == config.direction)
        entry = analyze_entry(data, event, structure, config, gates)
        # Combined screening modes must actually satisfy their selected rules.
        if not gates or (config.bos_confirmation and not entry["bos_confirmed"]) or (config.ob_retest and entry["ob_retest_date"] is None):
            continue
        rows.append(dict(event, stock_code=ticker.split('.')[0], stock_name=name,
                         market_structure=structure["states"][-1]["structure"],
                         breakout_pct=(event["signal_close"]/event["level"]-1)*100,
                         volume_ratio=float(bar.volume_ratio), traded_value=float(bar.trading_value),
                         macd_status=macd_status, current_price=float(data.Close.iloc[-1]),
                         matched_rules="; ".join(["Confirmed "+config.direction+" CHOCH", "Close crossed protected level + buffer",
                             "Signal-date volume ratio passed", "Signal-date traded value passed"]
                             + (["MACD cross confirmed"] if config.macd_confirmation else [])
                             + (["Weekly structure confirmed"] if config.weekly_filter else [])
                             + (["Subsequent BOS confirmed"] if config.bos_confirmation else [])
                             + (["Order block retest confirmed"] if config.ob_retest else [])),
                         analysis_date=data.index[-1], fresh=fresh, **entry))
    return rows, dict(data=data, structure=structure, other_structure=other, indicators=indicators)


def scan(universe, histories, config, calendar, asof, progress=None):
    rows, details, issues = [], {}, {}
    for i, stock in enumerate(universe.to_dict("records")):
        ticker = stock["ticker"]
        try:
            if ticker not in histories:
                raise ValueError("No cached/downloaded daily history")
            found, detail = analyze_stock(histories[ticker], ticker, stock.get("stock_name", stock.get("name", "")), config, calendar, asof)
            rows.extend(found)
            if found:
                details[ticker] = detail
        except (ValueError, KeyError, TypeError) as error:
            issues[ticker] = str(error)
        if progress:
            progress(i+1, len(universe))
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.drop_duplicates("signal_id").sort_values(["signal_date", "ticker"], ascending=[False, True])
    return dict(results=frame, details=details, issues=issues, config=config,
                asof=pd.Timestamp(asof).isoformat(), stocks_scanned=len(universe))


def notification_snapshot(entry_results, sent_ids=()):
    """Final CURRENT delivery list, displayed before any manual send action."""
    if entry_results.empty:
        return entry_results.copy()
    return entry_results.loc[entry_results.fresh & entry_results.entry_status.isin(["READY", "TRIGGERED"])
                             & ~entry_results.signal_id.isin(sent_ids)].copy(deep=True)
