import math
from .order_blocks import find_order_block, retest_at
from .bos_detector import subsequent_bos


def analyze_entry(data, signal, structure, config, confirmations=True):
    bullish = signal["direction"] == "BULLISH"
    sign = 1 if bullish else -1
    invalidation = signal["invalidation_level"]
    zone = find_order_block(data, signal, config.ob_lookback)
    bos = subsequent_bos(structure, signal)
    ob_touch = retest_at(data, signal, zone)
    level_touch = retest_at(data, signal, dict(low=signal["level"], high=signal["level"]))
    trigger = {"BREAKOUT": signal["signal_date"], "RETEST": level_touch,
               "ORDER_BLOCK": ob_touch, "BOS": bos["signal_date"] if bos else None}[config.entry_mode]
    gates = confirmations and (not config.bos_confirmation or bos is not None) and (not config.ob_retest or ob_touch is not None)
    status = "WAIT"
    entry = stop = target = risk = None
    if invalidation is not None:
        stop = invalidation * (1-sign*config.stop_buffer)
        # The latest completed close is a reference; execution occurs next session.
        entry = float(data.Close.iloc[-1])
        risk = sign*(entry-stop)
        if math.isfinite(risk) and risk > 0 and stop > 0:
            target = entry + sign*config.target_r*risk
            status = "TRIGGERED" if gates and trigger is not None else "READY" if gates else "WAIT"
    if trigger is None and status == "TRIGGERED":
        status = "READY"
    after = data.iloc[signal["position"]:]
    invalid = (not after.valid_bar.all() or invalidation is None or risk is None or risk <= 0
               or (target is not None and target <= 0))
    if stop is not None:
        invalid |= bool((after.Low <= stop).any() if bullish else (after.High >= stop).any())
    if invalid:
        status, target = "INVALIDATED", None
    return dict(entry_status=status, entry_price=entry, stop_loss=stop, target_price=target,
                risk_reward=config.target_r if target is not None else None,
                bos_confirmed=bos is not None, bos_date=bos["signal_date"] if bos else None,
                ob_low=zone["low"] if zone else None, ob_high=zone["high"] if zone else None,
                ob_date=zone["candle_date"] if zone else None, ob_retest_date=ob_touch,
                trigger_date=trigger, risk_per_share=risk)
