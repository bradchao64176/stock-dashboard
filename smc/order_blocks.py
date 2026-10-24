def find_order_block(data, signal, lookback=10):
    end = signal["position"]
    for i in range(end-1, max(-1, end-lookback-1), -1):
        row = data.iloc[i]
        if not row.valid_bar:
            break
        opposite = row.Close < row.Open if signal["direction"] == "BULLISH" else row.Close > row.Open
        if opposite:
            return dict(low=float(row.Low), high=float(row.High), candle_date=data.index[i],
                        activated_at=signal["signal_date"])
    return None


def retest_at(data, signal, zone):
    if zone is None:
        return None
    for i in range(signal["position"]+1, len(data)):
        row = data.iloc[i]
        if not row.valid_bar:
            return None
        bullish = signal["direction"] == "BULLISH"
        if (bullish and row.Close < zone["low"]) or (not bullish and row.Close > zone["high"]):
            return None
        touched = row.Low <= zone["high"] and row.High >= zone["low"]
        held = row.Close >= zone["high"] if bullish else row.Close <= zone["low"]
        if touched and held:
            return data.index[i]
    return None
