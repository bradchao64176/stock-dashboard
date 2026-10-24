def choch_events(structure):
    return [event for event in structure["events"] if event["kind"] == "CHOCH"]
