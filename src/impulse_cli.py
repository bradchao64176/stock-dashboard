"""Service-backed Impulse scanner; cached validation may specify historical bounds."""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from services.backtest_history import load_incremental_histories
from services.taiwan_universe import fetch_taiwan_universe
from src.impulse_macd import ImpulseConfig, calculate_impulse, scan_impulse_universe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=str(date.today() - timedelta(days=365)))
    parser.add_argument("--end", default=str(date.today() + timedelta(days=1)))
    parser.add_argument("--universe-csv", help="Previously retrieved official universe, for offline validation")
    parser.add_argument("--limit", type=int, default=20, help="0 scans the full universe")
    parser.add_argument("--lookback", type=int, default=5)
    parser.add_argument("--output", default="validation/impulse_macd")
    parser.add_argument("--strong", action="store_true")
    parser.add_argument("--compare", action="store_true", help="Run A–F through the existing backtest engine")
    args = parser.parse_args()
    import pandas as pd
    if args.universe_csv:
        universe = pd.read_csv(args.universe_csv, dtype={"stock_code": str})
        universe_errors = {}
    else:
        universe, universe_errors = fetch_taiwan_universe()
    if args.limit:
        if args.strong:
            universe = pd.concat([universe[universe.market == "TWSE"].head((args.limit + 1) // 2),
                                  universe[universe.market == "TPEx"].head(args.limit // 2)])
        else:
            universe = universe.head(args.limit)
    histories, errors = load_incremental_histories(universe.ticker.tolist(), args.start, args.end, Path("data/unfilled_gap_prices.db"), refresh_lookback_months=1)
    config = ImpulseConfig(cross_lookback_days=args.lookback)
    revenue_errors = {}
    if args.strong:
        from services.monthly_revenue import load_monthly_revenue
        from src.strong_impulse import scan_strong_universe
        revenues, revenue_errors = load_monthly_revenue(Path("data/unfilled_gap_prices.db"))
        result = scan_strong_universe(universe, histories, revenues, config, download_errors=errors)
    else:
        result = scan_impulse_universe(universe, histories, config, errors)
    checks = []
    for event in result["events"].to_dict("records"):
        data = result["details"][event["ticker"]]
        prefix = calculate_impulse(data.loc[:event["signal_date"]], config)
        last, previous = prefix.iloc[-1], prefix.iloc[-2]
        checks.append(dict(ticker=event["ticker"], date=str(event["signal_date"]),
                           valid=bool(last.Impulse_MACD > last.Impulse_Signal and previous.Impulse_MACD <= previous.Impulse_Signal
                                      and abs(last.Impulse_MACD - event["Impulse_MACD"]) < 1e-9)))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for name in ("candidates", "events", "issues"):
        result[name].to_csv(output / (name + ".csv"), index=False, encoding="utf-8-sig")
    report = dict(stats=result["stats"], market_date=str(result["market_date"]), universe_errors=universe_errors,
                  revenue_errors=revenue_errors,
                  requested_start=args.start, requested_end_exclusive=args.end, config=vars(config), checks=checks,
                  all_checks_passed=all(c["valid"] for c in checks))
    if args.strong:
        selected = result["candidates"]
        condition_columns = [c for c in selected if c.startswith("condition_")]
        report["all_selected_conditions_pass"] = bool(selected[condition_columns].all().all()) if not selected.empty else True
        report["revenue_observed_at"] = str(revenues.available_at.max()) if not revenues.empty else None
    if args.compare:
        from services.monthly_revenue import load_monthly_revenue
        from backtesting.impulse import compare_impulse_variants
        if not args.strong:
            revenues, revenue_errors = load_monthly_revenue(Path("data/unfilled_gap_prices.db"))
        research = compare_impulse_variants(universe, histories, revenues, config)
        for name in ("comparison", "trades", "signals", "forward_returns", "all_signals"):
            research[name].to_csv(output / ("backtest_" + name + ".csv"), index=False, encoding="utf-8-sig")
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
