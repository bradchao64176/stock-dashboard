# Entry Timing LINE source-of-truth fix

The canonical DataFrame returned by Entry Timing analysis, after the existing liquidity filter, supplies both the displayed Entry Timing table and manual LINE notification. The table uses a presentation copy for column selection and status labels without changing its rows.

## Session state

Each page stores its canonical DataFrame independently:

- `impulse_macd_entry_results`
- `bear_flag_entry_results`
- `bear_flag_gap_entry_results`
- `unfilled_gap_entry_results`
- `bear_flag_backtest_entry_results`

Each corresponding `<scanner_id>_entry_metadata` stores analysis timestamp, scanner name, trading-value threshold, filter enabled state, and candidate count. The UI displays the analysis timestamp used by LINE.

## Eligibility and sending

`get_line_eligible_candidates` now returns a deep copy of every displayed row. The old `LINE_ELIGIBLE_ENTRY_STATUSES` constant and `.loc[entry_status.isin(...)]` selection were removed. No status, liquidity, price, or risk filtering occurs in LINE. All row values and order are preserved, including WATCH, EXTENDED, HIGHLY_EXTENDED, and other statuses. Each message retains its Entry Status label.

A defensive count check prevents sending on any mismatch. The preview cache version changed so existing sessions cannot reuse previews produced by the old filtering policy.

Preview and send share the same frozen message payload. The manual callback validates its binding to the saved analysis using a fingerprint and timestamp. A changed snapshot is rejected pending review. No scanner rerun, Yahoo download, SQLite query, or Entry Timing recalculation occurs in the callback. Backtest sends use the displayed current Entry analysis, never historical trades or a separate scanner lookup.

## Files changed for this fix

- `services/entry_line_notification_service.py`
- `src/entry_line_panel.py`
- `tests/test_manual_entry_line.py`
- `tests/test_entry_line_source.py` (new)
- `MANUAL_LINE.md`
- `validation/entry_line_source/REPORT.md` (new)

Other existing worktree changes predate this fix.

## Validation

`python -m unittest discover -s tests -q`: **205 tests passed**.

The A–G regression scenario runs against all five page identities:

| Measurement | Count |
|---|---:|
| Displayed Entry Timing analysis | 18 |
| LINE candidate rows (A through R) | 18 |
| Preview stocks | 18 |
| Actual mocked send stocks | 18 |

Tests verify exact preview/payload equality, page isolation, unchanged row values, snapshot protection, and no recalculation/data access during the send action. These are test counts, not a live market scan. All LINE API calls are mocked; no real notifications were sent.

LINE notification now uses the displayed Entry Timing Analysis result as its single source of truth. No scanner rerun or Yahoo download occurs when the LINE button is pressed. Scanner algorithms and market-data pipelines were not changed by this fix.
