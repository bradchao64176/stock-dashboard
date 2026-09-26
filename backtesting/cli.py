"""Small-sample validation and reproducible CSV exports: python -m backtesting.cli."""
import argparse
from dataclasses import asdict
from datetime import date, timedelta
import json
from pathlib import Path

import pandas as pd

from backtesting.config import BacktestConfig
from backtesting.engine import build_signal_set, execute_backtest
from backtesting.signals import generate_signals, prepare_history
from services.backtest_history import load_backtest_histories
from services.taiwan_universe import fetch_taiwan_universe

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CODES = "2330,2317,2454,2303,2308,2603,2609,2615,2409,3481,5483,3293,6488,8069,3260,3105,6182,5347,6274,6187"


def audit_trades(result, raw_histories, config, limit=5):
    """Rebuild selected signals from truncated raw data and verify execution anchors."""
    if result["trades"].empty:
        return []
    trades = result["trades"]
    primary = trades[(trades.RR_target == 2) & (trades.max_holding_days == 20)]
    # Review different outcomes where available, then fill chronologically.
    picked = pd.concat([primary.groupby("outcome", sort=True).head(1), primary.head(limit)])
    picked = picked.drop_duplicates("signal_id").head(limit)
    audits = []
    for _, trade in picked.iterrows():
        raw = raw_histories[trade.ticker].copy()
        if raw.index.tz is not None:
            raw.index = raw.index.tz_localize(None)
        past = raw.loc[:trade.signal_date]
        stock = {key: trade[key] for key in ("ticker", "stock_code", "stock_name", "market")}
        signals = generate_signals(prepare_history(past, config), stock, config,
                                   signal_start=trade.signal_date, signal_end=trade.signal_date)
        assert len(signals) == 1, "Signal depends on future data"
        assert abs(signals[0]["bull_flag_score"] - trade.bull_flag_score) < 1e-8
        next_day = raw.index[raw.index.get_loc(trade.signal_date) + 1]
        assert trade.entry_date == next_day
        assert abs(trade.entry_price - raw.loc[next_day, "Open"]) < 1e-8
        assert abs(trade.target_price - (trade.entry_price + 2 * trade.risk_per_share)) < 1e-8
        if config.stop_method == "FLAG_LOW":
            assert abs(trade.stop_price - past.loc[trade.flag_start:trade.flag_end, "Low"].min()) < 1e-8
        audits.append({key: trade[key] for key in ("ticker", "signal_date", "entry_date", "entry_price",
                       "stop_price", "target_price", "exit_date", "exit_price", "outcome", "MFE_R", "MAE_R",
                       "same_bar_ambiguous")})
    return audits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codes", default=SAMPLE_CODES)
    parser.add_argument("--years", type=int, choices=[1, 2, 3, 5, 10], default=2)
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", default="validation/bull_flag_backtest")
    args = parser.parse_args()
    config = BacktestConfig()
    end = date.fromisoformat(args.end)
    start = (pd.Timestamp(end) - pd.DateOffset(years=args.years)).date()
    universe, roster_errors = fetch_taiwan_universe()
    requested = {c.strip() for c in args.codes.split(",")}
    stocks = universe[universe.stock_code.isin(requested)].sort_values("ticker")
    if stocks.empty:
        raise RuntimeError(f"No official sample stocks: {roster_errors}")
    print(f"Official sample: {len(stocks)} stocks. Downloading {start} through {end} plus warmup.", flush=True)
    histories, download_errors = load_backtest_histories(
        tuple(stocks.ticker), start - timedelta(days=240), end + timedelta(days=1),
        ROOT / "data" / "backtest_prices.db", refresh=args.refresh,
        progress=lambda done, total: print(f"Downloaded batch {done}/{total}", flush=True))
    bundle = build_signal_set(stocks, histories, config, str(start), str(end),
                              progress=lambda done, total: print(f"Analyzed {done}/{total}", flush=True))
    result = execute_backtest(bundle, config, evaluation_end=str(end))
    audits = audit_trades(result, histories, config)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    result["trades"].to_csv(output / "trades.csv", index=False, encoding="utf-8-sig")
    result["comparison"].to_csv(output / "rr_comparison.csv", index=False, encoding="utf-8-sig")
    result["signals"].to_csv(output / "signals.csv", index=False, encoding="utf-8-sig")
    result["skipped"].to_csv(output / "skipped.csv", index=False, encoding="utf-8-sig")
    report = dict(start=str(start), end=str(end), generated_at=result["generated_at"],
                  requested_codes=sorted(requested), sample=stocks.to_dict("records"), config=asdict(config),
                  stats=result["stats"], roster_errors=roster_errors, download_errors=download_errors,
                  issues=result["issues"], audits=audits)
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str), flush=True)
    table = result["comparison"]
    print(table[table.max_holding_days == 20][["RR_target", "total_signals", "total_trades", "wins", "losses", "timeouts",
                                             "censored", "win_rate", "expectancy", "profit_factor", "maximum_drawdown"]].to_string(index=False))


if __name__ == "__main__":
    main()
