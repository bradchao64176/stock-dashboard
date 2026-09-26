"""Validate the gap scanner on a small sample, then optionally the full universe."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from backtesting.cli import SAMPLE_CODES
from backtesting.config import BacktestConfig
from backtesting.signals import prepare_history, generate_signals
from services.taiwan_universe import fetch_taiwan_universe
from services.yahoo_history import download_histories
from src.bull_flag_gap import (scan_gap_universe, normalize_dates, gap_zone, fill_state,
                               corporate_action_mask, observed_sessions)
from src.bull_flag_gap_config import GapConfig


def audit_candidates(result, histories):
    """Recheck every returned stock directly against source rows and a T-only prefix."""
    audits = []
    config = result["config"]
    sessions = observed_sessions(histories)
    for _, event in result["candidates"].iterrows():
        raw = normalize_dates(histories[event.ticker])
        aligned = raw.reindex(sessions[sessions >= raw.index[0]])
        data = prepare_history(aligned, BacktestConfig(detector=config.detector))
        bp, gp = int(event.breakout_signal_index), int(event.gap_index)
        prefix = data.iloc[:bp + 1]
        stock = {k: event[k] for k in ("stock_code", "stock_name", "ticker", "market")}
        signals = generate_signals(prefix, stock, BacktestConfig(detector=config.detector, require_breakout_volume=False),
                                   signal_start=prefix.index[-1])
        assert len(signals) == 1, "Historical Bull Flag signal not reproducible"
        sig = signals[0]
        assert sig["MA20"] > sig["MA60"] and sig["MA20_slope"] > 0
        assert sig["close"] > sig["upper_flag_trendline"]
        zone = gap_zone(data.iloc[gp], data.iloc[gp - 1], config.gap_definition, config.min_gap_pct)
        assert zone is not None
        assert abs(zone["gap_top"] - event.gap_top) < 1e-8
        assert len(data) - 1 - bp < config.gap_lookback_days
        assert len(data) - 1 - gp < config.gap_lookback_days
        assert not corporate_action_mask(data, config).iloc[data.index.get_loc(event.flagpole_start):].any()
        state = fill_state(data, gp, zone)
        assert state["fill_data_complete"] and state["gap_status"] != "FILLED"
        assert state["gap_status"] == event.gap_status
        assert abs(state["gap_fill_pct"] - event.gap_fill_pct) < 1e-8
        if config.require_gap_volume_confirmation:
            assert event.breakout_volume_ratio >= config.min_breakout_volume_ratio
        audits.append(dict(ticker=event.ticker, breakout_date=str(event.breakout_date.date()),
                           gap_date=str(event.gap_date.date()), gap_bottom=event.gap_bottom,
                           gap_top=event.gap_top, gap_status=event.gap_status, gap_fill_pct=event.gap_fill_pct,
                           age=int(event.trading_days_since_gap), prefix_verified=True))
    return audits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Full current TWSE/TPEx common-stock universe")
    parser.add_argument("--codes", default=SAMPLE_CODES)
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--output", default="validation/bull_flag_gap_sample")
    args = parser.parse_args()
    config = GapConfig(gap_lookback_days=args.lookback)
    universe, errors = fetch_taiwan_universe()
    if not args.full:
        universe = universe[universe.stock_code.isin([s.strip() for s in args.codes.split(",")])]
    if universe.empty:
        raise RuntimeError(f"No official stock universe: {errors}")
    print(f"Universe {len(universe)} stocks; lookback {config.gap_lookback_days} sessions", flush=True)
    histories, failures = download_histories(tuple(universe.ticker), actions=True,
                                             progress=lambda done, total: print(f"Downloaded {done}/{total}", flush=True))
    result = scan_gap_universe(universe, histories, config,
                               progress=lambda done, total: print(f"Analyzed {done}/{total}", flush=True)
                               if done % 100 == 0 or done == total else None)
    audits = audit_candidates(result, histories)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    result["candidates"].to_csv(output / "candidates.csv", index=False, encoding="utf-8-sig")
    result["events"].to_csv(output / "events.csv", index=False, encoding="utf-8-sig")
    universe.to_csv(output / "universe.csv", index=False, encoding="utf-8-sig")
    # Preserve only event stocks' raw histories for review, not a duplicate warehouse.
    for ticker in result["details"]:
        histories[ticker].to_csv(output / (ticker + ".csv"), index_label="Date", encoding="utf-8-sig")
    report = dict(config=asdict(config), stats=result["stats"], market_date=str(result["market_date"]),
                  scan_time=result["scan_time"], universe_errors=errors, download_errors=failures,
                  issues=result["issues"], audits=audits)
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("stats", "market_date", "universe_errors", "download_errors", "audits")},
                     ensure_ascii=False, indent=2, default=str), flush=True)
    if result["stats"]["analyzed"] == 0:
        raise RuntimeError("No stocks analyzed; validation did not succeed")


if __name__ == "__main__":
    main()
