"""Strict confirmed pivots. Equal extrema never qualify; invalid bars break windows."""
from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class Pivot:
    kind: str
    price: float
    pivot_time: pd.Timestamp
    confirmed_at: pd.Timestamp
    position: int
    confirmed_position: int
    label: str


def confirmed_pivots(data, left=5, right=5):
    previous = {}
    valid = data.valid_bar.to_numpy(dtype=bool)
    values = {"High": data.High.to_numpy(dtype=float), "Low": data.Low.to_numpy(dtype=float)}
    for i in range(left + right, len(data)):
        pos = i - right
        if not valid[pos-left:i+1].all():
            previous.clear()
            continue
        for kind, column, greater in (("HIGH", "High", True), ("LOW", "Low", False)):
            value = float(values[column][pos])
            before, after = values[column][pos-left:pos], values[column][pos+1:i+1]
            if not (((value > before).all() and (value > after).all()) if greater
                    else ((value < before).all() and (value < after).all())):
                continue
            old = previous.get(kind)
            label = kind if old is None else (("HH" if value > old else "LH" if value < old else "EQH")
                                             if greater else ("HL" if value > old else "LL" if value < old else "EQL"))
            confirmed = pd.Timestamp(data.available_at.iloc[i]) if 'available_at' in data else data.index[i]
            yield Pivot(kind, value, data.index[pos], confirmed, pos, i, label)
            previous[kind] = value
