"""Small-sample then full-market validation of the MA-filtered gap strategy."""
import argparse
from dataclasses import asdict
from datetime import date, timedelta
import json
from pathlib import Path

import pandas as pd

from backtesting.cli import SAMPLE_CODES
from services.backtest_history import load_backtest_histories
from services.taiwan_universe import fetch_taiwan_universe
from src.bull_flag_gap import normalize_dates, observed_sessions, fill_state, gap_zone
from src.unfilled_gap import scan_unfilled_universe, prepare_trend_history, trend_values, trend_passes
from src.unfilled_gap_config import UnfilledGapConfig

ROOT = Path(__file__).resolve().parents[1]


def audit_candidates(result, histories):
    cfg = result["config"]
    sessions = observed_sessions(histories)
    audits = []
    for _, event in result["candidates"].iterrows():
        raw = normalize_dates(histories[event.ticker])
        aligned = raw.reindex(sessions[sessions >= raw.index[0]])
        data = prepare_trend_history(aligned, cfg)
        gp = int(event.gap_index)
        historical = prepare_trend_history(aligned.iloc[:gp + 1], cfg)
        values = trend_values(historical.iloc[-1], "gap_day")
        values.update(trend_values(data.iloc[-1], "current"))
        for key in ("gap_day_ma20", "gap_day_ma60", "gap_day_ma20_slope_pct", "current_ma20",
                    "current_ma60", "current_ma20_slope_pct", "current_ma60_slope_pct"):
            if pd.isna(values[key]) and pd.isna(event[key]):
                continue
            assert abs(values[key] - event[key]) < 1e-8, f"Historical timing error: {key}"
        if cfg.trend.trend_evaluation != "CURRENT":
            assert trend_passes(values, "gap_day", cfg.trend)
        if cfg.trend.trend_evaluation != "GAP_DAY":
            assert trend_passes(values, "current", cfg.trend)
        assert event.recent_return_pct + 1e-12 >= cfg.min_return_pct
        assert 0 <= event.trading_days_since_gap < cfg.gap_lookback_days
        zone = gap_zone(data.iloc[gp], data.iloc[gp - 1], cfg.gap_definition, cfg.min_gap_pct)
        assert zone is not None
        state = fill_state(data, gp, zone)
        assert state["fill_data_complete"] and state["gap_status"] in ("UNTOUCHED", "PARTIALLY_FILLED")
        assert abs(state["gap_fill_pct"] - event.gap_fill_pct) < 1e-8
        audits.append(dict(ticker=event.ticker, gap_date=str(event.gap_date.date()),
                           gap_status=event.gap_status, recent_return_pct=event.recent_return_pct,
                           gap_day_verified=True, current_verified=True, fill_history_verified=True))
    return audits


def run(stocks, cfg, output, roster_errors, refresh=False):
    end = date.today() + timedelta(days=1)
    start = (pd.Timestamp(date.today()) - pd.DateOffset(years=1)).date()
    print(f"Scanning {len(stocks)} stocks", flush=True)
    histories, failures = load_backtest_histories(tuple(stocks.ticker), start, end,
        ROOT / "data" / "unfilled_gap_prices.db", refresh=refresh, actions=True,
        progress=lambda done, total: print(f"Downloaded {done}/{total}", flush=True))
    result = scan_unfilled_universe(stocks, histories, cfg,
        progress=lambda done, total: print(f"Analyzed {done}/{total}", flush=True)
        if done % 100 == 0 or done == total else None)
    if not result["stats"]["analyzed"]:
        raise RuntimeError("No stocks analyzed")
    audits = audit_candidates(result, histories)
    output.mkdir(parents=True, exist_ok=True)
    result["candidates"].to_csv(output / "candidates.csv", index=False, encoding="utf-8-sig")
    result["events"].to_csv(output / "events.csv", index=False, encoding="utf-8-sig")
    stocks.to_csv(output / "universe.csv", index=False, encoding="utf-8-sig")
    report = dict(config=asdict(cfg), stats=result["stats"], market_date=str(result["market_date"]),
                  scan_time=result["scan_time"], universe_errors=roster_errors,
                  download_errors=failures, issues=result["issues"], audits=audits)
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("stats", "market_date", "universe_errors", "download_errors")},
                     ensure_ascii=False, indent=2), flush=True)
    if not result["candidates"].empty:
        print(result["candidates"][["stock_code", "stock_name", "market", "gap_date", "recent_return_pct",
                                     "gap_pct", "gap_status", "unfilled_gap_score"]].head(20).to_string(index=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    universe, errors = fetch_taiwan_universe()
    if universe.empty:
        raise RuntimeError(f"Official universe unavailable: {errors}")
    cfg = UnfilledGapConfig()
    sample = universe[universe.stock_code.isin(SAMPLE_CODES.split(","))]
    run(sample, cfg, ROOT / "validation" / "unfilled_gap_sample", errors, args.refresh)
    if args.full:
        run(universe, cfg, ROOT / "validation" / "unfilled_gap_full", errors, args.refresh)


if __name__ == "__main__":
    main()
