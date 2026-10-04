# Shared manual Entry LINE notifications

## Use

Run any of the four live selection pages normally. Beneath its existing results
and charts, Entry Timing shows the same candidate stocks with reference entry
zones, stops and risk-unit targets. Below it, expand **📋 預覽 LINE 訊息**, then
press **📲 發送符合進場條件股票到 LINE** to send. Preview does not send anything.
Zero eligible stocks displays `目前沒有符合進場條件的股票。` and disables Send.

Supported pages / isolated session keys:

| Page | Entry results key | Send button key |
|---|---|---|
| Impulse MACD 黃金交叉選股 | impulse_macd_entry_results | line_push_impulse_macd |
| 台股下降旗形選股 | bear_flag_entry_results | line_push_bear_flag |
| 下降旗形多方缺口突破 | bear_flag_gap_entry_results | line_push_bear_flag_gap |
| 多方未回補缺口選股 | unfilled_gap_entry_results | line_push_unfilled_gap |
| 下降旗形策略回測 | bear_flag_backtest_entry_results | line_push_bear_flag_backtest |

The Impulse section also supports the Pure preset, without requiring revenue or
a Strong qualification for those already-selected Pure candidates. Turning off
Strong-only display does not silently reapply Strong selection to Entry Timing.
Existing scanner algorithms and their filter semantics are unchanged.

## Shared layers

1. Existing scanners select stocks and retain snapshots, unchanged.
2. `services/scanner_entry_service.py` adapts selected rows and in-memory history.
3. `services/entry_timing_service.py` uses the existing shared formulas. Its
   default STRONG mode is preserved; IMPULSE validates the real golden cross;
   SIGNAL accepts the scanner's own signal candle. A forming flag has no signal
   candle, so its cross zone is N/A; pullback/breakout remain possible. A combined
   flag/gap uses the later recognition date, when both facts were available.
4. `src/entry_line_panel.py` caches Entry results by page, snapshot and displayed
   candidate selection, then calls the existing Entry detail renderer. Send
   reruns reuse those results instead of calculating indicators again.
5. `services/entry_line_notification_service.py` formats, chunks and
   sends the exact saved preview only from the button callback.
6. `services/line_bot_service.py` performs the LINE Messaging API request.

The checkout had no existing LINE client or automatic monitor/scheduler source
to reuse. The shared client reads `LINE_CHANNEL_ACCESS_TOKEN` and `LINE_USER_ID`
from the project-root `.env` file (independent of the working directory).
Explicit process environment variables take priority. The file is read on each
manual send, so file edits do not require restarting Streamlit. It creates no
channel, recipient, token, database table or background job. No credentials are rendered, persisted,
logged, or committed. No real LINE messages are sent during tests or setup.

## Eligibility and message content

Every row of the final displayed Entry Timing snapshot is a LINE candidate.
`get_line_eligible_candidates()` returns a deep copy without status filtering.
There are no secondary price, risk, zone, volume, or liquidity checks, sorting
or deduplication. Entry Status remains visible in each message.
The displayed row order and values are preserved. Incomplete values are formatted
as N/A, never replaced by values from another source or silently dropped.

The same saved `<scanner>_entry_results` frame is supplied to the Entry table and
the notification component. `<scanner>_entry_metadata` records the analysis
timestamp, scanner name, liquidity threshold/enabled state and total row count.
Both UI sections display the analysis timestamp. The button displays the exact
displayed row count. These are analysis-time values, not a claim of live prices.

Each message contains the scanner name, Asia/Taipei timestamp, total eligible
count, part number, stock code/name, price data date, current price, entry type,
entry RANGE, MA20/distance, MACD/signal/histogram/direction, reference stop, risk %,
2R and 3R reference targets. Source fields include golden-cross date/zone/score,
flag resistance/high/low/date, or gap prices/percentage/status as applicable.

The preview timestamp and text are frozen while results are unchanged. Every
LINE request sends that exact preview text. Default maximum is five stocks per
text; UTF-16 length checks split earlier if needed. For 13 ordinary-size stocks,
the three messages contain 5/5/3 stocks and `第 1/3 則` etc. Each API request
contains one text message, respecting LINE's message limits.

## Strict manual behavior

The only UI send path is the explicit button's `on_click` callback. Page loads,
scan completion, filters, candidate changes, preview and reruns cannot send.
No send action queries market data, reruns a scanner, updates prices, modifies
source results or touches automatic monitor state/deduplication.

Each rendered send action has a UUID. The callback consumes it before IO, so
replaying the same Streamlit event cannot send twice. Each chunk has a stable
LINE retry key derived from that action. A later deliberate click gets a new
UUID and may resend identical stocks; automatic intraday dedup is not used.
There are no automatic retries. Partial failure reports accepted chunks/stocks
and stops; deliberately pressing Send again resends the complete preview.
Success means LINE accepted the request, not a delivery/read receipt. Network
timeouts can leave delivery uncertain. Errors use safe static text/HTTP codes,
never raw exception bodies, authorization headers or recipient identifiers.

LINE references: [push API and text limits](https://developers.line.biz/en/reference/messaging-api/nojs/),
[retry keys](https://developers.line.biz/en/docs/messaging-api/retrying-api-request).

## Backtest safeguard

Backtest trades, historical winners/losers, and backtest price histories are
never inputs to the send component. The backtest page draws only from the most
recent live Bull Flag scanner snapshot in this same Streamlit session, applies
its configured scanner thresholds, and requires BREAKOUT on the latest completed
weekday candle. The snapshot must have been scanned today in Asia/Taipei, with
matching latest history dates. Its Entry analysis is stored under the backtest's
own key and messages identify the Backtest page as their source.

Freshness uses the existing 14:00 completed-daily cutoff, weekends and saved
timestamps without any market request. On weekday holidays or uncertainty it
fails closed rather than treating an older candle as current. The UI explains
that the live Bull Flag scan must be run first. These checks occur when building
the displayed Entry analysis, never inside LINE sending. On click, the callback
checks only the saved analysis fingerprint/timestamp against the preview and
rejects a replaced snapshot. It never retrieves raw scanner rows. No scheduler
or calendar service is modified.

## Verification

`python -m unittest tests.test_manual_entry_line -q` mocks all LINE traffic.
The tests cover manual-only sends, all displayed statuses, NaNs/invalid
prices, exact preview, chunking, distinct scanner state, repeated events,
deliberate resend, safe and partial failures, current-only backtest sources,
unchanged source frames, and no database/download/recalculation on Send.
Existing tests exercise all five scanner pages and original selection logic.
See `validation/manual_line/REPORT.md` for final counts and database integrity.
