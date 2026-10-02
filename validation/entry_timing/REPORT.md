# Entry Timing verification

Baseline checkout: ade9efa. Existing suite before edits: 130 tests PASS.
New Entry Timing suite: 31 tests PASS.
Final `python -m unittest discover -s tests -q`: 161 tests PASS (14.587s).
`git diff --check`: PASS.

| Component | Result |
|---|---|
| Daily/Bull Flag/Gap scanners | PASS, existing suites |
| Impulse MACD | PASS |
| Strong Golden Cross | PASS, nonempty real scanner output retained unchanged |
| HistoricalDataService / Yahoo request behavior | PASS, existing suites; source unchanged |
| Backtesting engine | PASS, existing suites; source unchanged |
| Entry Timing core and UI | PASS |
| Intraday Monitor | Not testable: source/tests absent in this checkout |
| LINE notifications | Not testable: source/tests absent in this checkout |
| SQLite daily_prices integrity | PASS, before/after content hash identical |

Production database was opened read-only for inspection. No refresh or migration
was invoked. Both snapshots have 477,139 rows, 1,978 tickers, minimum date
2025-09-26 and maximum date 2026-09-24. Ordered ticker/date/payload SHA-256:
`7fa38578613c0962027c16cb0a6f77aced7b0444c2468ee11f9dc6c30776106f`.
See database_before.json and database_after.json.

Coverage includes all requested zone/status, histogram, ATR, swing, stop, risk,
2R/3R, missing input, and no-look-ahead cases. Additional checks cover old cross
expiry in sessions, overlapping pattern priority, configurable volume behavior,
invalid risk suppression, raw-history prefix equivalence, no SQLite/Yahoo IO,
unchanged input frames/candidates/scores, and full existing-page integration
without repeat downloads. No real Yahoo requests or LINE sends were made.

Files added: services/entry_timing_config.py, services/entry_timing_service.py,
src/entry_timing_panel.py, tests/test_entry_timing.py, ENTRY_TIMING.md,
and validation/entry_timing/{REPORT.md,database_before.json,database_after.json}.
Existing application file modified: src/impulse_panel.py (3 additive lines).
The environment also appends command transcripts to powershell.log.
