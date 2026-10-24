# SMC / CHOCH delivery validation

Date: 2026-10-18. Branch: `feature/smc-choch`.

## Delivered workflow

Sidebar **SMC / CHOCH Stock Screener** → Market All, symbols blank, maximum
stocks 0 → **Download Yahoo prices and scan CHOCH**. The existing company roster
enumerates TWSE/TPEx common stocks. Yahoo Finance supplies daily OHLCV, using the
existing unchanged downloader. All enumerated stocks are attempted; unavailable
data is reported, not replaced by stale cached history. Results explain matched
CHOCH rules. Optional MACD, weekly, BOS and order-block filters must pass when
selected. Neither the original MA trend rule nor revenue rule is imposed.

Daily/weekly structures, independent entry analysis, CSV, selectable chart
overlays and manually triggered LINE delivery are included. The normal scan
does not write daily_prices. A separate approved ledger protects CHOCH sends.

## Files

Added `smc/`: config, pivots, market_structure, choch_detector, bos_detector,
calendar, data, timeframes, order_blocks, scanner, entry_analysis,
notification_repository, notifications, migrate, backtest, cli and package init.

Added UI: `pages/6_SMC_CHOCH.py`, `src/smc_choch_panel.py`,
`src/smc_choch_chart.py`.

Added tests: `tests/test_smc_engine.py`, `tests/test_smc_integration.py`.
Added documentation: `docs/SMC_CHOCH.md` and this validation directory.

Modified existing production source: `src/navigation.py` only, one new page link.
PowerShell also appended its existing `powershell.log`; it was not reverted.

## Actual checks

- `python -m unittest discover -s tests -q`: **234 tests, PASS** (30.768 seconds).
- CHOCH-only suite: **24 tests, PASS**. Yahoo and LINE mocked.
- Existing 210 tests included in the full suite.
- Existing data-file SHA-256 hashes match the implementation baseline;
  `integrity.txt` records no changed existing data files.
- `git diff --check`: PASS, with the repository's LF/CRLF informational warning.
- New `data/smc_choch.db` initialized after approval; no old schema migration.
- No real LINE message was sent during development/tests.
- Full live Yahoo download was not executed in this validation session. Download
  dispatch across 1,200 mocked universe symbols, default all-stock settings and
  independent failure handling are covered by tests.
- Chart dates/domain shapes and crosshair settings are tested programmatically;
  native mouse/zoom interaction was not manually exercised in this session.
- Intraday job source is absent in this checkout; its live scheduled execution
  cannot be certified. Existing scheduler/notification files were not changed.

## Research artifacts

`final_cached_comparison/` holds the final offline comparison using 1,981 cached
Yahoo histories, as of 2026-10-07. It is distinct from a fresh full-market scan.
`cached_comparison/` is an earlier conservative-calendar experiment and must not
be used as the final comparison. Execution assumptions, actual metrics and
trades are exported together. See the operating documentation for costs,
confirmation delays, survivorship, realized drawdown and short-sale limitations.
No strategy superiority is asserted.

Final offline run completed successfully over all 1,981 cached symbols:

| Strategy | Trades | Win rate | Mean return | Realized drawdown | Profit factor | Mean sessions |
|---|---:|---:|---:|---:|---:|---:|
| Pure Impulse MACD (long), comparison execution model | 6,845 | 39.15% | 0.49% | -38.62% | 1.78 | 13.86 |
| CHOCH | 525 | 45.14% | 1.98% | -29.53% | 2.07 | 17.52 |
| CHOCH + MACD | 151 | 45.70% | 3.17% | -14.20% | 3.90 | 17.80 |
| CHOCH followed by BOS | 164 | 53.66% | 6.75% | -19.32% | 3.40 | 19.19 |

These are exploratory results from cached data with different signal counts,
not an out-of-sample performance claim or a capital-constrained portfolio model.

## Operation and rollback

Start with `streamlit run app.py`. The existing pages remain available. The
CHOCH manual LINE preview shows the exact final delivery snapshot; sending does
not rerun the scanner or prices. Stable signal IDs prevent duplicate sends.

Rollback consists of removing the new navigation link and new feature files,
then archiving the separate CHOCH ledger with the app stopped. Keep the ledger
history if re-enabling notifications. Do not modify existing databases.

Full algorithm, settings, availability rules and research limitations:
`docs/SMC_CHOCH.md`.
