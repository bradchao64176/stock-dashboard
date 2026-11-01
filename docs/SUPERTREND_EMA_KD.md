# Independent Supertrend + EMA200 + KD Scanner

This scanner is **Daily-only**, including indicators, filters, charts and LINE
results. Weekly and Dual modes were removed at the user's request. Existing SMC
and other strategies retain their own timeframe support.

Start `streamlit run app.py`, select **Supertrend + EMA200 + KD Scanner**, leave
TWSE and TPEx checked, and press **Scan all eligible stocks**. There is no sample
limit or upstream candidate dependency. The exchange company roster supplies
common-stock symbols/names; Yahoo Finance supplies OHLCV. Four-digit ordinary
company codes are mapped to `.TW` or `.TWO` using exchange membership. Existing
roster exclusions for ETFs, ETNs, preferred shares, warrants and TDRs are reused.

## Architecture and scope

- `strategies/supertrend_kd.py`: immutable settings and pure calculations.
- `services/supertrend_scanner.py`: full-universe execution and optional downstream
  shared Entry Timing adapter. It imports no MACD/CHOCH candidate scanner.
- `services/supertrend_data.py`: existing cache read-only, isolated missing-range
  cache, validation and observed Yahoo sessions.
- `services/supertrend_line.py`: exact displayed-match preview and manual delivery.
- `services/supertrend_cli.py`: live scan or explicitly offline coverage study.
- `src/supertrend_panel.py`, `pages/7_Supertrend_EMA_KD.py`: independent UI/state.
- Only existing production source changed: one link in `src/navigation.py`.

No original scanner, Entry Timing formula, Yahoo service, scheduler, intraday
service or notification workflow was changed. No commit or push was performed.

## Rules and conventions

Default Daily mode requires Close > EMA200, bullish Supertrend, Close >
Supertrend, deviation 0–10%, K < 40, D < 40, and K > D with previous K <= D.
**Enable EMA Filter** defaults to checked, with editable **EMA period = 200**.
When enabled, Close must exceed EMA of that period. When disabled, only that
condition is skipped; Supertrend, KD, deviation and traded-value rules remain.
EMA is still calculated for chart/reference display when enough data exists.
Disabled EMA does not impose its history requirement: readiness uses the remaining
indicator periods plus the configured additional warm-up.

Minimum traded value is TWD100M. Deviation and traded-value filters can be disabled;
periods, multiplier, KD ceiling, warm-up and thresholds are editable on the page.

EMA uses an initial period SMA, then alpha=2/(period+1). Default additional
warm-up is 50 candles, so default readiness requires 250 valid daily
consecutive candles. Supertrend uses ATR10, Wilder SMA-seeded RMA, multiplier3,
trailing upper/lower bands, and initializes bearish. The recurrence follows
[TradingView's Supertrend definition](https://www.tradingview.com/support/solutions/43000634738-supertrend/).

KD is Taiwan-style 9/3/3 recursive smoothing: RSV=100*(Close-lowest Low9)/
(highest High9-lowest Low9); K=(2*previous K+RSV)/3; D=(2*previous D+K)/3,
initial K/D=50. Periods/smoothing are configurable. It is not SMA-smoothed STOCH.
Flat RSV windows are UNKNOWN and cannot produce a cross.

Deviation=100*(Close/Supertrend-1). Volume is shares. Traded value uses the shared
official-amount preference, otherwise daily Close*Volume in TWD.

The scan requests approximately 515 calendar days at default settings to cover
EMA200 plus 50 daily warm-up bars. Actual sufficient daily candle count is checked.
Only completed daily candles are used, with the existing 14:00 Asia/Taipei cutoff.
There is no weekly aggregation, weekly confirmation, or multi-year weekly request.

## Data safety and cache

`data/unfilled_gap_prices.db` is opened with SQLite `mode=ro` and query_only.
New missing bars/coverage use `data/supertrend_prices.db`, created only when a
scan needs persistence. It uses the existing `daily_prices` and `history_coverage`
schema conventions; no existing database schema is migrated. Inserts are
INSERT OR IGNORE; neither existing valid bars nor legacy records are overwritten.

The existing Yahoo downloader remains interval1d, auto_adjust=False, batch40,
threads4, failed-symbol retries2 with exponential backoff. Only uncovered ranges
are requested, with seven-day boundary overlaps. OHLC revisions in these overlaps
produce DATA_CONSISTENCY_ERROR and preserve the cache. There is no silent mixed
basis or automatic database rebuild. Empty responses preserve cached history.

Yahoo OHLC is normally already split-adjusted even with auto_adjust=False. No
second split is applied. An action-day open/previous-close discontinuity >25%
is rejected conservatively; source corrections are not silently inferred. This
does not guarantee detection of every provider error. See the provider's
[missing split adjustment discussion](https://github.com/ranaroussi/yfinance/blob/main/doc/source/advanced/price_repair.rst).
Cash dividends are not additionally adjusted in this strategy.

Invalid/missing/zero-volume individual stock candles interrupt indicator warm-up.
The common session grid comes from Yahoo histories. Flat zero-volume dates are
excluded as no-trade dates only when at least two supplied symbols corroborate
them and no supplied stock has positive volume. This is observed Yahoo evidence,
not an authoritative closure calendar: a market-wide provider outage could look
similar. Unreported recent weekdays remain expected and cause STALE status.
Recent listings, historical suspensions and data gaps may fail the 250-consecutive-
daily-bar requirement even when total history is long. No threshold is relaxed silently.

## Results, Entry Timing and LINE

The snapshot reports eligible, processed, downloaded, cached, evaluated, matched,
excluded, insufficient, stale and errored counts plus per-ticker audit reasons.
Download error details can coexist with usable cached history. Partial exchange
rosters are visibly flagged. Matches/audit are exportable as CSV.

Entry Timing is an optional button acting only on matches and saved daily data.
Its classifications do not change Supertrend matches. Chart/CSV/Entry/LINE reruns
do not trigger downloads or another scan. State keys start `supertrend_ema_kd_`.

The displayed strategy matches are the exact LINE preview/send list. Sending
occurs only on the explicit button, using the existing LINE transport and .env
credentials. Each signal ID includes strategy version, ticker, timeframe and
signal date. A separate `supertrend_notifications` table in the new strategy
database atomically reserves the whole preview. SENT, UNCERTAIN and crash-PENDING
reservations prevent duplicate sends across restarts. An uncertain delivery
requires manual review; no automatic retry or automatic scanner notification.
No original LINE dedup state is changed. No real LINE was sent during validation.

## Validation and operation

`python -m unittest discover -s tests -q`

`python -m services.supertrend_cli` runs the full current exchange universe.
`--timeframe Daily` is optional; non-daily arguments are rejected. `--offline` explicitly
analyzes cached symbols at the latest cached date; it is not proof of current
full exchange coverage. Initial missing history is downloaded; later requests
reuse coverage. A manual stop of the application is not a background scheduler.

Fresh Yahoo verification CSVs and per-condition output are under
`validation/supertrend/yahoo/`; `verify_yahoo --saved` reuses those exact downloads.
Current verification includes two symbols, not a complete live-market run.

Rollback: remove the new sidebar link and new strategy files; archive the isolated
strategy database with the application stopped. Preserve notification reservations
if later re-enabling sends. Leave all original databases and features intact.
