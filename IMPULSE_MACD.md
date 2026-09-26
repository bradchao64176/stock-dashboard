# Impulse MACD 黃金交叉選股

Independent strategy; existing Bull Flag, gap, news and backtest pages are preserved.
No new dependencies.

Run `python -m streamlit run app.py`, then open **Impulse MACD 黃金交叉選股**
in the sidebar. Market **All** scans the entire current official common-stock
universe. Data acquisition runs only on submitting the scan form. Stock selection,
chart inspection, CSV export and histogram filtering reuse the completed snapshot.

## Calculation

- HLC3 = (High + Low + Close) / 3.
- SMMA high/low: initial 34-bar SMA, then `(previous * 33 + price) / 34`.
- EMA uses pandas `ewm(span=length, adjust=False)`, seeded with the first source
  observation. ZLEMA = 2 × EMA(HLC3) − EMA(EMA(HLC3)).
- MACD is distance beyond the SMMA channel, or zero inside it. Values remain
  missing until SMMA warmup completes. Signal is the 9-bar simple average;
  histogram is MACD minus signal.
- Golden cross requires current MACD > signal AND previous MACD <= signal.
  Zero plateaus never emit repeated events merely because MACD remains above signal.
- All lengths are configurable. Missing/invalid OHLCV, zero volume and missing
  observed market sessions reset warmup rather than bridging unknown candles.

Default lookback 5 means latest five sessions (ages 0–4). Both 0 and 1 mean only
the latest completed session. All recent events are retained; the table displays
each stock's latest qualifying event. An intervening bearish cross does not erase
a historical golden cross. Optional current histogram > 0 filters the current
table without changing historical event records.

Positive impulse and optional Close > MA20, MA20 > MA60, MA20 rising filters apply
on the **crossover date**. Defaults are off. Near-zero classification uses absolute
tolerance 1e-10; the crossover comparison itself uses no tolerance.

The supplied request ends during section 16. Consequently, **Current histogram > 0**
is an explicitly labeled provisional confirmation option, off by default. No
unprovided scoring formula or additional strategy rules have been inferred.

## Storage and architecture

- `src/impulse_macd.py`: config, SMMA, indicators, historical event generator,
  universe scanner. No network calls or yfinance imports.
- `services/backtest_history.py`: additive `load_incremental_histories` service;
  the existing snapshot API remains compatible with other pages.
- Reuses **data/unfilled_gap_prices.db**, importing existing action-inclusive
  snapshots into daily rows once per ticker. `daily_prices` has a unique
  (ticker,date) key and UPSERT updates; `history_coverage` tracks successful
  acquisition ranges, including holidays. Requests are batched by missing range.
  Legacy snapshots remain for existing callers; no Impulse-specific price DB exists.
- Earlier requested ranges are backfilled; later ranges fetch missing tails.
  Failed ranges remain retryable. Incomplete refreshes are reported and excluded
  from candidates. Unfinished daily bars are excluded using the existing 14:00
  Taipei cutoff. Cached historical vendor revisions are not automatically refetched.
  Missing interior vendor bars in an already covered range also require an
  explicit data repair; the scanner will not interpolate them into signals.
- `src/impulse_panel.py`, `pages/5_Impulse_MACD.py`: Streamlit controls and chart.
- `src/impulse_cli.py`: service-backed command-line scan and prefix audit exports.
- `src/navigation.py`: shared left-menu link (the home label remains
  `stock-dashboard Apps`).

`historical_cross_events` returns causal event-day snapshots, signal ID/date/index,
price, indicator values and strategy identifier. It does not select trades using
today's surviving signals. A future backtest adapter must explicitly choose a stop
model and supply ATR/stop inputs to the existing execution engine; this feature
does not introduce a duplicate execution engine or claim historical profitability.

## Commands

```powershell
python -m unittest discover -s tests -q
python -m src.impulse_cli --limit 20
python -m src.impulse_cli --limit 0 --output validation/impulse_macd_full
```

Automated validation: 117 tests passed, including 12 new indicator, timing,
incremental-cache, failure-retry and Streamlit integration tests.

Offline validation using the already retrieved official universe and cached bars:

```powershell
python -m src.impulse_cli --start 2025-09-26 --end 2026-09-25 --universe-csv validation/unfilled_gap_full/universe.csv --limit 20
```

End dates are exclusive. The sample analyzed 18 of 20 stocks, skipped 2 invalid or
insufficient latest histories, and found 3 candidates as of 2026-09-24:
1103.TW (September 22), 1108.TW (September 23), 1210.TW (September 18).
All three recomputed prefix-only crossover checks passed. These are cached-data
validation results, not a fresh live-market or profitability backtest claim.

Full cached-universe validation (same dates and defaults): 1,978 histories available,
1,757 analyzed, 221 skipped for invalid/latest missing bars or insufficient warmup,
432 candidates (253 TWSE, 179 TPEx). Of these, 52 crossed on September 24.
All 433 recent crossover events passed prefix-only reconstruction checks.
Results: `validation/impulse_macd_full/candidates.csv`, `events.csv`, `issues.csv`
and `validation.json`. Optional positive-zone and MA filters were **off**.

## Limitations

Raw Yahoo OHLC is used; splits/dividends can affect indicators. EMA initialization
and available history length can cause small differences from chart platforms.
The observed cross-stock session calendar cannot detect a date missing from every
download. Current listings imply survivorship bias. The scanner reports latest
observed dates and data errors; it cannot guarantee vendor completeness or accuracy.
