def subsequent_bos(structure, signal):
    return next((event for event in structure["events"] if event["kind"] == "BOS"
                 and event["direction"] == signal["direction"] and event["parent_id"] == signal["signal_id"]
                 and event["position"] > signal["position"]), None)
