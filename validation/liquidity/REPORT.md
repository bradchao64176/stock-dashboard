# Trading Value filter delivery verification

Baseline: 186 tests PASS. New liquidity suite: 16 tests PASS, including a
table-driven test that scans all five pages with the default threshold and
then disables it to restore the original result charts. Final full suite:
`python -m unittest discover -s tests -q` — **202 tests PASS**, 30.155 seconds.

| Regression | Result |
|---|---|
| Impulse MACD / Strong Golden Cross | PASS |
| 台股下降旗形選股 | PASS |
| 下降旗形多方缺口突破 | PASS |
| 多方未回補缺口選股 | PASS |
| 下降旗形策略回測 | PASS |
| Entry Timing Engine | PASS |
| Manual LINE Push | PASS, mocked only |
| Daily Historical Data | PASS |
| SQLite daily_prices | PASS, content hash unchanged |

Both database snapshots: 485,020 rows, 1,978 tickers, dates 2025-09-26 through
2026-10-02. Ordered-row SHA-256:
`517967b8fead9ebef1c2b556e4e0fbd7c1b4af660e8ee6d54bb067263155a238`.
See before.json and after.json. Inspection used read-only SQLite. No production
market refresh, migration, deletion or data write was performed.

Coverage includes 150M pass, exact 100M pass, 99.99M fail, disabled/custom/preset
settings, missing values, explicit shares/lots conversion, official amount
precedence, exact historical signal dates, no future-volume influence, filtered
LINE previews, nonmutation, zero extra market/database calls, and page-specific
session persistence. Legacy UI fixtures use deliberately small volumes; their
tests now disable the optional post-filter explicitly to preserve the original
technical-scanner assertions. Separate tests cover enabled-by-default behavior.

## Files created

- services/liquidity_filter.py
- src/liquidity_panel.py
- tests/test_liquidity_filter.py
- LIQUIDITY_FILTER.md
- validation/liquidity/{before.json,after.json,REPORT.md}

## Files modified in this task

- src/impulse_panel.py
- src/bull_flag_panel.py
- src/bull_flag_gap_panel.py
- src/unfilled_gap_panel.py
- src/backtest_panel.py
- src/entry_line_panel.py — current backtest candidates pass the same filter.
- src/entry_timing_panel.py — display trading-value metadata.
- services/scanner_entry_service.py — carry trading-value metadata.
- services/entry_line_notification_service.py — add one formatted amount line.
- tests/test_impulse_macd.py
- tests/test_bull_flag_panel.py
- tests/test_bull_flag_gap_panel.py
- tests/test_unfilled_gap_panel.py
- tests/test_backtest_storage_ui.py
- tests/test_entry_timing.py

The environment also appends powershell.log; an ignored test_run.log records
intermediate testing. Earlier uncommitted LINE/Entry/menu changes were retained.
Scoped diff whitespace checks passed. A general diff check reported pre-existing
trailing whitespace in src/navigation.py, which this task did not alter.

All scanner/indicator formulas, Entry Timing formulas, market-data services,
SQLite schema and backtesting execution engine remain unchanged. LINE's send
logic remains explicit manual-click-only; only message content gains the amount.
