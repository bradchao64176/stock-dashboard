# Supertrend / EMA200 / KD verification

## Daily-only correction

The user subsequently restricted this scanner to **Daily only**. Weekly/Dual
UI choices, calculations and confirmation requirements have been removed from
the Supertrend module. Configuration/CLI reject non-daily modes; stale non-daily
session snapshots cannot be displayed or sent. Default history requests now use
515 calendar days for 200 daily EMA bars plus 50 warm-up bars. Daily formulas,
full-universe selection and existing strategies are unchanged. The historical
Weekly/Dual verification below is retained as an audit of the earlier version,
not a list of currently supported modes.

Completed 2026-10-24. No commit/push or real LINE delivery performed.

## Fresh Yahoo verification

Eight years of Yahoo daily OHLCV were downloaded successfully for **2330.TW**
and **3293.TWO**, through 2026-10-23, with no download errors. The downloader was
the unchanged shared service (`interval=1d`, `auto_adjust=False`, actions enabled).
Network access required escalation because the first restricted attempt failed.

Each symbol supplied 1,941 dated rows. Two common flat, zero-volume dates were
excluded by the new strategy's Yahoo no-trade handling, leaving 1,939 observed
daily bars and 412 completed weekly aggregates. Latest actual trading data is
2026-10-22; 2026-10-23 contains a flat zero-volume placeholder in both downloads.
The raw CSVs remain intact under `yahoo/` for audit. Indicators and condition flags
are in the six corresponding Daily/Weekly/Dual CSVs. No further network request
was needed when rerunning calculations after the fixes.

| Stock / mode | Close | EMA | Supertrend | K | D | Latest outcome |
|---|---:|---:|---:|---:|---:|---|
| 2330.TW Daily | 2385 | 2158.20 | 2518.48 | 9.97 | 18.29 | Excluded: Supertrend/deviation/KD |
| 2330.TW Weekly | 2385 | 1326.05 | 2258.26 | 49.58 | 66.34 | Excluded: KD |
| 2330.TW Dual | 2385 | 2158.20 | 2518.48 | 9.97 | 18.29 | Excluded: daily Supertrend/deviation/KD |
| 3293.TWO Daily | 787 | 755.93 | 753.11 | 40.30 | 47.31 | Excluded: KD |
| 3293.TWO Weekly / Dual | 787 | Weekly unavailable | — | — | — | Insufficient consecutive valid weekly history |

3293.TWO has individual historical zero-volume dates, most recently 2025-03-10.
These invalidate the associated week and restart the conservative warm-up.
The scanner does not manufacture missing prices or relax readiness to obtain a
match. Total row count alone is not evidence of 250 consecutive usable weeks.

Historical signal flags on the same downloaded data: 2330.TW Daily 8, Weekly 1,
Dual 3; 3293.TWO Daily 9, Weekly/Dual 0. These are historical rule matches, not
current candidates or a backtest of trading returns.

## Issues discovered and corrected through real Yahoo data

1. Market-wide flat zero-volume placeholders previously reset indicators. The
   isolated strategy now excludes corroborated no-trade dates; individual-stock
   missing/suspended rows still invalidate continuity. The inference is recorded
   and is not represented as an authoritative exchange calendar.
2. Yahoo already adjusts historical OHLC for splits in normal responses. A split
   event no longer automatically wipes weekly EMA warm-up; large unresolved
   action-day price discontinuities remain invalid. Cache-overlap conflicts still
   fail closed without overwriting cached prices.

## Coverage study and tests

- Full local cached universe: 1,981 tickers, as of 2026-10-16.
- Evaluated: 1,561; excluded by rules: 1,561; matches: 0.
- Insufficient: 418; stale: 2; calculation errors: 0.
- Cached study downloaded no data and is distinct from the fresh two-stock test.
- Full live exchange-universe scan was **not** executed. Dispatch tests prove all
  1,200 supplied roster members are scanned, with no MACD/CHOCH candidate dependency.
- Existing baseline: 234 tests PASS. Final suite: **261 tests PASS**, including
  27 new tests (48.048 seconds). Yahoo/LINE mocked in automated tests; real Yahoo
  downloads were a separate explicitly invoked verification.
- Tests cover suffix mapping, independent exchange selection, incremental cache
  reuse, empty/failed downloads, price revision conflicts, correct KD transition,
  deviation/liquidity boundaries, weekly warm-up, no future-week use, per-stock
  isolation, chart dates/crosshair, exact preview/send and manual deduplication.
- Existing database hashes unchanged. Original daily_prices: **503,553 rows,
  1,981 tickers, 2025-09-26 through 2026-10-16**. No production schema modified.
- `git diff --check` passed, with the repository's LF/CRLF informational warning.

## Files and limitations

Added: `strategies/__init__.py`, `strategies/supertrend_kd.py`,
`services/supertrend_data.py`, `services/supertrend_scanner.py`,
`services/supertrend_line.py`, `services/supertrend_cli.py`,
`src/supertrend_panel.py`, `pages/7_Supertrend_EMA_KD.py`,
`tests/test_supertrend.py`, `docs/SUPERTREND_EMA_KD.md`, and validation artifacts.

Only existing production source modified: `src/navigation.py`, one sidebar link.
PowerShell appended its existing log. Existing formulas, services and notification
schedules were not changed. The new scanner optionally consumes shared Entry
Timing only after selection. New cache/notification tables are isolated in
`data/supertrend_prices.db`, created lazily by scanning/sending; they do not alter
existing databases. Validation did not send messages or create that production
strategy cache.

Known limits: Yahoo-wide outages can resemble no-trade days; unknown weekday
closures without corroborating data fail closed as stale; gaps can delay weekly
readiness; price revision conflicts require review. Native mouse/zoom behavior
was not manually exercised, although Plotly crosshair/date properties passed.
Live intraday/scheduler execution was not tested; those files remain untouched.

See `docs/SUPERTREND_EMA_KD.md` for operation, formulas, cache and rollback details.
