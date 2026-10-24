"""Prefix-stable swing/internal state machines, evaluated only at candle closes."""
from dataclasses import asdict
import hashlib
from .pivots import confirmed_pivots


def signal_id(symbol, timeframe, structure_type, direction, pivot, signal_time, kind):
    structure_id = f"{pivot.kind}:{pivot.pivot_time.isoformat()}:{pivot.price:.12g}"
    key = "|".join((symbol, timeframe, structure_type, direction, structure_id, signal_time.isoformat(), kind))
    return hashlib.sha256(key.encode()).hexdigest(), structure_id


def analyze_structure(data, symbol, config, structure_type="SWING"):
    left, right = ((config.swing_left, config.swing_right) if structure_type == "SWING"
                   else (config.internal_left, config.internal_right))
    pivots = list(confirmed_pivots(data, left, right))
    by_time = {}
    for pivot in pivots:
        by_time.setdefault(pivot.confirmed_position, []).append(pivot)
    high = low = protected_high = protected_low = None
    trend, transition, parent = "UNKNOWN", None, None
    events, states, consumed = [], [], set()
    transition_at = -1
    last_break_level = last_break_time = None
    closes, valid = data.Close.to_numpy(), data.valid_bar.to_numpy()
    for i, row in enumerate(data.itertuples()):
        day = row.Index
        previous_trend = trend
        if not row.valid_bar:
            high = low = protected_high = protected_low = None
            trend, transition, parent = "UNKNOWN", None, None
            last_break_level = last_break_time = None
        else:
            for p in by_time.get(i, []):
                if p.kind == "HIGH":
                    high = p
                else:
                    low = p
            if high and low:
                if trend == "UNKNOWN":
                    if high.label == "LH" and low.label == "LL":
                        trend = "BEARISH"
                        protected_high, protected_low = high, low
                    elif high.label == "HH" and low.label == "HL":
                        trend = "BULLISH"
                        protected_high, protected_low = high, low
                elif trend == "TRANSITION":
                    if transition == "BULLISH" and protected_low and row.Close < protected_low.price:
                        trend, transition, parent = "BEARISH", None, None
                    elif transition == "BEARISH" and protected_high and row.Close > protected_high.price:
                        trend, transition, parent = "BULLISH", None, None
                    elif (transition == "BULLISH" and low.position > transition_at and low.label == "HL"
                          and high.position > transition_at):
                        trend = "BULLISH"
                        protected_low = low
                    elif (transition == "BEARISH" and high.position > transition_at and high.label == "LH"
                          and low.position > transition_at):
                        trend = "BEARISH"
                        protected_high = high
            # Protected reversal levels are updated on continuation breaks, not every pivot.
            choices = []
            if trend == "BEARISH":
                choices = [("CHOCH", "BULLISH", protected_high), ("BOS", "BEARISH", low)]
            elif trend == "BULLISH":
                choices = [("CHOCH", "BEARISH", protected_low), ("BOS", "BULLISH", high)]
            for kind, direction, pivot in choices:
                if pivot is None or i == 0 or not valid[i-1] or i-pivot.position > config.lookback:
                    continue
                sign = 1 if direction == "BULLISH" else -1
                level = pivot.price * (1 + sign * config.breakout_buffer)
                crossed = sign * (row.Close-level) > 0 and sign * (closes[i-1]-level) <= 0
                key = (pivot.kind, pivot.pivot_time, direction)
                if not crossed or key in consumed:
                    continue
                consumed.add(key)
                ident, structure_id = signal_id(symbol, config.timeframe, structure_type, direction, pivot, day, kind)
                opposite = low if direction == "BULLISH" else high
                events.append(dict(signal_id=ident, structure_id=structure_id, ticker=symbol,
                                   timeframe=config.timeframe, structure_type=structure_type, kind=kind,
                                   direction=direction, signal_date=day, confirmed_at=getattr(row,'available_at',day), position=i,
                                   level=pivot.price, break_threshold=level, signal_close=float(row.Close),
                                   invalidation_level=opposite.price if opposite else None,
                                   previous_structure=trend, parent_id=parent if kind == "BOS" else None,
                                   pivot_time=pivot.pivot_time, pivot_confirmed_at=pivot.confirmed_at))
                last_break_level, last_break_time = pivot.price, day
                if kind == "CHOCH":
                    trend, transition, parent, transition_at = "TRANSITION", direction, ident, i
                    protected_high, protected_low = high, low
                else:
                    protected_high, protected_low = high, low
                break
        states.append(dict(date=day, structure=trend, previous_structure=previous_trend,
                           transition=transition, protected_high=protected_high.price if protected_high else None,
                           protected_low=protected_low.price if protected_low else None,
                           latest_high=high.price if high else None, latest_low=low.price if low else None,
                           break_level=last_break_level, break_time=last_break_time))
    return dict(events=events, pivots=[asdict(p) for p in pivots], states=states)
