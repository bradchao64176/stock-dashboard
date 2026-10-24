# SMC / CHOCH Stock Screener

## Operation

Run `streamlit run app.py` in the project directory. Select **SMC / CHOCH Stock
Screener** in the sidebar. Default Market = All, Maximum stocks = 0 (all),
and optional symbol selection = blank. Press **Download Yahoo prices and scan
CHOCH**. This downloads Yahoo Finance daily prices for all TWSE/TPEx common
stocks in the existing company roster, then applies the configured CHOCH rules.
The company roster supplies symbols/names only; Yahoo supplies prices.

The existing downloader is reused unchanged: `interval="1d"`,
`auto_adjust=False`, bounded batches and failed-symbol retries. Four years of
history provide weekly warmup. Prices remain in the isolated CHOCH snapshot;
no new download is performed on chart/filter/preview/LINE reruns. Download failures
and incomplete market rosters are visible. No stale cache substitution occurs
in the normal Yahoo scan. Optional CLI `--cache-only` is explicitly offline research.

Results list matching confirmed CHOCH events within the selected signal age,
with a `matched_rules` explanation, direction, structure, protected break level,
volume ratio, traded value, and independent entry/risk analysis. Combined MACD,
weekly, BOS and order-block modes require their selected conditions to pass.
No Close > MA20 > MA60 or monthly revenue condition is imposed.

## Independent components

`smc/` contains immutable configuration, confirmed pivots, structure/CHOCH/BOS,
order blocks, timeframe/data adapters, scanner, entry analysis, notification
ledger/delivery, and backtest/CLI code. `src/smc_choch_panel.py` and
`src/smc_choch_chart.py` contain only the new feature's UI/chart behavior.
`pages/6_SMC_CHOCH.py` is the new entry point. The only existing production source
modified is `src/navigation.py`, adding one link. Existing scanner implementations,
history services, Entry Timing, LINE services and chart helper are unchanged.

## Causal rules

- Strict high/low pivots require all left/right candles. Equal extrema do not
  qualify. Each pivot stores its candle and confirmation time. Same-side pivots
  remain separate immutable observations; comparisons are to the prior same-side
  confirmed pivot. Invalid windows reset comparisons.
- LH/LL establishes bearish structure; HH/HL establishes bullish structure.
  A protected reversal level is set on establishment and continuation breaks.
- CHOCH requires a close beyond the protected level plus buffer and a previous
  close not already beyond it. Wicks alone do not qualify. Each level/direction
  can break once. Structure IDs use pivot identity, not moving row offsets.
- CHOCH enters TRANSITION. A later confirmed post-CHOCH HL/high (or LH/low)
  establishes the new direction; a later continuation close produces BOS.
  A BOS links to its parent CHOCH and cannot occur on the same signal candle.
- Swing and internal calculations are separate. Defaults: 5/5 and 3/3 pivots,
  60-candle structural level age, 0.5% break buffer, 10-candle recent-signal window.
- Signal-time volume ratio uses the previous 20 valid completed candles, excluding
  the signal bar. Default minimum 1.5. Traded value default TWD 100M, using the
  existing official-amount preference or raw Close × share-volume estimate.
- Daily bars complete at the existing conservative 14:00 Taipei cutoff.
  Weekly OHLCV aggregates completed sessions; weekly monetary value sums daily
  amounts. Partial/missing weeks do not become confirmed valid candles.
- No TWSE calendar API is called. Within downloaded history coverage, sessions
  use the union of positive-price, positive-volume Yahoo dates across stocks.
  Missing individual-stock sessions invalidate continuity. Outside this coverage,
  weekdays remain expected so old data cannot silently become current. Optional
  supplied closure dates are excluded. Yahoo alone cannot distinguish a
  market-wide data outage from a closure; this remains a data-coverage limitation.
  Weekly confirmation waits until Friday at 14:00 Taipei, including holiday weeks;
  backtests cannot execute before this availability timestamp.
- Raw corporate-action bars reset structure; historical adjustments are not
  silently applied. Future provider revisions can change source data; prefix
  stability applies to identical input bars and calendar assumptions.

## Entry analysis and charts

Entry modes: BREAKOUT, RETEST, ORDER_BLOCK, BOS. Order block = last valid opposing
candle before the break within the configured search window; full wick zone.
It activates at CHOCH, and retest requires a later overlap and close beyond the
zone in the reversal direction. Crossing the far edge invalidates that retest.

WAIT means a configured confirmation is absent. READY means confirmations pass
but the selected trigger is pending; TRIGGERED means it has occurred. INVALIDATED
means the structural stop was breached, continuity was lost, or risk is invalid.
References use the latest completed close, not a guaranteed historical fill.
Stop = opposite structural extreme with a configurable safety buffer. Targets
use configurable R multiples (default 2R). Long/short price ordering is validated;
zero/negative risk or a nonpositive target is not a valid setup.

Charts reuse the existing crosshair/date helpers. Price, volume and Impulse
panels share dates. Pivot labels disclose confirmation timing. Overlay categories
are selectable; level shapes use domain references, and reference levels cannot
stretch the initial candlestick scale. Zoom/pan remain Plotly interactions.

## Manual LINE and database safety

The separate final **CHOCH Entry Analysis — current LINE candidates** table is
the exact preview/send source. It contains fresh READY/TRIGGERED rows that have
not previously been reserved. The notification formatter does not rescan,
recalculate or select stocks. One text message per signal preserves its stable ID.

`data/smc_choch.db` was explicitly approved and initialized. Only
`smc_notifications` is added, in this new database. Credentials still come from
the existing transport's environment/project `.env`; they are never stored here.
Existing price/news/intraday databases are untouched.

`python -m smc.migrate` is a dry run. `--apply` creates a missing ledger only and
refuses to overwrite one. No production schema migration exists. Rollback: remove
the new navigation link/revert new feature files, close the app, then archive the
CHOCH ledger. Do not archive/delete it merely to resend: it contains dedup history.
Before any future ledger migration use SQLite's backup API, dry-run/version check,
and an explicit rollback plan; no such upgrade runs automatically.

The entire reviewed list is reserved in one transaction before sending. Duplicate
IDs abort a stale/concurrent send. Accepted sends become SENT; failures or unknown
outcomes remain UNCERTAIN (or PENDING if the process crashes). There is no automatic
retry. These records require manual delivery review; blindly deleting reservations
can cause duplicates. HTTP success means provider acceptance, not a read receipt.

## Research and validation

The page can compare the existing Pure Impulse crossover formula with CHOCH,
CHOCH+Impulse confirmation and CHOCH→BOS, using the saved histories. The original
Impulse strategy code is not edited. This research adapter uses its own explicit
stop/target rules; it is not a claim to reproduce every old backtest preset.

CLI: `python -m smc.cli` downloads Yahoo for the whole supported universe.
`--symbols` is an optional explicit subset. `--cache-only` avoids network requests;
`--calendar-csv` accepts known closure dates (`date` column). Outputs include
comparison metrics, executed trades and assumptions.

Execution is next daily open, 1,000 shares, 20-day maximum, conservative stop-first
same-bar policy. Existing configurable cost defaults are reused: brokerage .1425%,
minimum TWD20 per side, sale tax .3%, slippage .05%. End-of-data and invalid/action
bar exposures are censored. Realized-equity drawdown is not marked-to-market
drawdown. No cross-stock capital cap is modeled. Bearish results are hypothetical:
borrow availability/cost and Taiwan short-sale constraints are not simulated.
Current-roster survivorship and provider revision bias remain. No superiority
claim is made without actual comparison evidence.

Run `python -m unittest discover -s tests -q`. Yahoo/LINE are mocked in automated
tests. Fixtures cover causal event identity, pivots, bullish/bearish CHOCH/BOS,
retests, entry invalidation, weekly completion, data immutability, all-universe
download dispatch, UI defaults, chart references and manual duplicate prevention.
