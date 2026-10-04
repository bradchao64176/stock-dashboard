# Manual Entry LINE delivery report

## Tests

- Before changes: 161 existing tests passed.
- New manual LINE suite: 22 tests, including table-driven cases for all statuses
  and all five scanner identifiers.
- Final full suite: `python -m unittest discover -s tests -q` — 183 tests PASS
  in 22.249 seconds.
- `git diff --check`: PASS.
- LINE requests were mocked throughout. No real LINE sends or market refreshes.

| Required regression | Result |
|---|---|
| Impulse MACD 黃金交叉選股 | PASS |
| 台股下降旗形選股 | PASS |
| 下降旗形多方缺口突破 | PASS |
| 多方未回補缺口選股 | PASS |
| 下降旗形策略回測 | PASS |
| Daily Historical Data | PASS; source unchanged |
| Shared Entry Timing | PASS; original default-mode tests retained |
| Shared LINE Bot | PASS with mocked API |
| Existing LINE Bot | Absent in checkout; shared client added |
| Intraday Monitor / automatic scheduler | Absent in checkout; no files/state changed |
| SQLite daily_prices | PASS; identical before/after hash |

## Data integrity

Both read-only audit snapshots contain 485,020 daily rows for 1,978 tickers,
from 2025-09-26 through 2026-10-02. Ordered ticker/date/payload SHA-256:
`517967b8fead9ebef1c2b556e4e0fbd7c1b4af660e8ee6d54bb067263155a238`.
See database_before.json and database_after.json. No notification tables were
added and no existing daily, intraday, revenue or automatic-monitor DB was written.

## Safety evidence

The sole UI send call is `_manual_click`, registered on the explicit Send
button. Tests prove page loads, scanner runs, Entry calculation, filtering and
reruns do not send. Preview text is compared to captured outbound payloads.
Send callbacks run with SQLite and Yahoo calls prohibited and Entry recomputation
prohibited. Original scanner dataframes remain unchanged after Entry analysis.
Backtest trades never enter the candidate adapter; current-only scanner snapshot
and expiry checks are tested. Every page has separate result/preview/event keys.
Same-event replay is suppressed; intentional later clicks can resend. Safe error
and partial-send accounting tests verify secrets are not displayed.

## Files

Created:

- services/scanner_entry_service.py
- services/entry_line_notification_service.py
- services/line_bot_service.py
- src/entry_line_panel.py
- tests/test_manual_entry_line.py
- MANUAL_LINE.md
- validation/manual_line/REPORT.md
- validation/manual_line/database_before.json
- validation/manual_line/database_after.json

Modified:

- services/entry_timing_service.py — optional existing-scanner signal modes;
  original STRONG behavior remains the default, same zone/stop/target formulas.
- src/entry_timing_panel.py — accepts cached analyses and namespaced keys.
- src/impulse_panel.py
- src/bull_flag_panel.py
- src/bull_flag_gap_panel.py
- src/unfilled_gap_panel.py
- src/backtest_panel.py

Only additive integration calls were made to the five scanner panels. Selection
algorithms, daily/intraday market-data pipelines, historical services, revenue,
backtesting execution and automatic-scheduler logic were not modified. The
environment also appended command transcripts to powershell.log.
