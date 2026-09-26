# Bull Flag Gap Breakout / 下降旗形多方缺口突破選股

An independent strategy alongside the original Bull Flag Scanner and Backtesting
Engine. No new dependencies. Start with `python -m streamlit run app.py` and select
**下降旗形多方缺口突破** in the sidebar. Select **0** for the maximum stock count to
scan all current common stocks in the selected market.

## Files and reuse

New files:

- `src/bull_flag_gap_config.py`: immutable gap thresholds and score weights.
- `src/bull_flag_gap.py`: event discovery, fill tracking, filtering and backtest adapter.
- `src/bull_flag_gap_panel.py`: independent UI and gap-zone chart.
- `src/gap_scan_cli.py`: small/full-universe live validation and candidate audits.
- `pages/3_下降旗形多方缺口突破.py`: page entrypoint.
- `tests/test_bull_flag_gap.py`, `tests/test_bull_flag_gap_panel.py`: deterministic tests.
- This document and `validation/bull_flag_gap_sample/`, `validation/bull_flag_gap_full/` reports.

Modified files:

- `services/yahoo_history.py`: optional `actions` flag, default false for existing callers.
- `src/bull_flag_panel.py`: existing cached downloader optionally retrieves corporate actions.
- `src/navigation.py`: add the independent page; retain all existing pages and labels.

Uses the existing official TWSE/TPEx universe, Yahoo batching/retries, Streamlit
cache, `prepare_history`, `generate_signals`, `detect_patterns`, Bull Flag Score,
and candlestick/MA/regression chart renderer. There is no second Bull Flag algorithm
or duplicate trade simulator. The gap module adds only event association and gap
preservation analysis. Existing scanner adjustment and backtest rules are unchanged.

## Rules

At historical breakout T, require `Close > MA20 > MA60` and positive MA20 slope,
plus the existing valid descending flag, controlled retracement and score threshold.
The regression excludes T and receives no rows after T. Price must close above
projected resistance with the preceding close below preceding resistance. The gap
and breakout occur on the same day by default. Optional window 1 or 2 permits a gap
within ±1 or ±2 observed market sessions. Both events must be within the lookback;
the combined setup becomes known only on the later event date.

- **FULL_GAP (default):** gap-day Low > previous session High. Bottom = previous
  High; top = gap-day Low. Original size = top − bottom.
- **OPEN_GAP:** gap-day Open > previous session High. Top = gap-day Open.
  Gap-day Low is included in fill tracking: an opening gap may partially or fully
  fill on the same day and must not be reported as untouched in that case.
- `gap_pct = size / bottom`; default minimum 1%, editable to 0/0.5/1/1.5/2/3/5%.
- Volume confirmation defaults on, with breakout volume / mean of the **previous
  20 bars**, excluding breakout day, >=1.2. The original Bull Flag Score retains
  its own component calculation; Gap Breakout Score is a separate metric.

The event records `breakout_MA20`, `breakout_MA60`, `breakout_MA20_slope` separately
from current `MA20`, `MA60` and trend score. The historical uptrend is mandatory;
current trend deterioration lowers score but does not independently invalidate an
otherwise preserved gap. Extended prices are not automatically excluded.

## Lookback and data completeness

Default `gap_lookback_days=20`; UI options are 5, 10, 20, 30, 60. The window includes
the latest observed market session: ages 0 through N−1 qualify. Weekends/calendar
days do not count. Age N is outside the last N sessions.

The market calendar is the union of dates with positive volume across the supplied
histories. It is a practical observed calendar, not an official exchange-calendar
service. The caller can supply `market_sessions` explicitly. Histories are aligned
to this calendar; missing stock sessions and zero volume break continuity. A stale
latest quote is skipped rather than treating a suspended stock's old bar as today.
With only a narrow sample, a session missing from all its sources cannot be detected.

Missing OHLC/volume within a setup resets the existing detector's warmup. Missing
or invalid post-gap sessions make `fill_data_complete=False`, and the event cannot
enter the default results. An observed fill date in incomplete data is only the
first observed fill, not a guaranteed earliest fill; these events remain available
internally for inspection, with the incomplete-data flag.

## Fill states — do not collapse them

For FULL_GAP, inspect only rows after the gap. For OPEN_GAP, include the gap-day Low.

| State | Rule |
| --- | --- |
| UNTOUCHED | No checked low <= gap top; with no later candles this is vacuously true |
| PARTIALLY_FILLED | A checked low <= top, but none <= bottom |
| FILLED | First checked low <= bottom; equality counts as full fill |

`gap_fill_pct = clip((top − minimum_checked_low) / original_size, 0, 1)`.
Exact contact with the top is PARTIALLY_FILLED with **0% depth**, not UNTOUCHED:
this preserves the strict `all_later_lows > gap_top` option.

Remaining size = original size × (1 − fill fraction). `remaining_gap_pct` is the
fraction of the **original gap** remaining; `remaining_gap_price_pct` is the
remaining size / original bottom. `lowest_price_after_gap` is subsequent-only;
`lowest_price_since_gap` includes the OPEN_GAP day's low. No subsequent observations
are represented by missing values, not a fabricated low.

The first full-fill date and its session offset are retained. A recovered price
cannot turn a previously FILLED gap back into an unfilled one. By default results
include UNTOUCHED and PARTIALLY_FILLED only. Optional **Only Untouched Gaps** removes
even zero-depth boundary touches. Users may explicitly include FILLED.

All valid event associations are retained, including filled gaps. Display filters
are applied **before** taking the most recent qualifying gap for each ticker; a
newer filled event must not hide an older valid unfilled one. Default ranking uses
Gap Breakout Score, descending. All events for a selected ticker can be inspected.

## Gap Breakout Score

Each fraction below is clipped to [0,1]; weights/denominators are centralized.

| Component | Points | Quality fraction |
| --- | ---: | --- |
| Bull Flag quality | 25 | existing Bull Flag Score / 100 |
| Breakout strength | 20 | (breakout close / resistance − 1) / 5% |
| Gap size | 15 | gap percentage / 5% |
| Breakout volume | 15 | breakout volume ratio / 3 |
| Gap preservation | 15 | 1 − gap fill fraction |
| Current trend | 10 | (current MA20/MA60 − 1) / 10%, only if current Close > MA20 > MA60 and positive slope |

FILLED gets zero preservation points. `gap_score_*` fields explain each component.
The score is a heuristic, not an estimated probability. `distance_from_gap_pct`
is `(current_close − original_top) / original_top` and is descriptive only.

## Corporate actions and price basis

Use unadjusted-by-Adj-Close Yahoo OHLC, as the historical engine does. Yahoo itself
may retrospectively split-adjust/revise OHLC, so this is not point-in-time archival
data. Retrieve available Dividends/Stock Splits/Capital Gains fields using the shared
downloader's `actions=True` option. Conservatively reject event setups spanning:

- reported corporate actions;
- Adj Close / Close factor changes exceeding 0.1%; or
- unexplained close-to-close changes exceeding 30%.

Both guards are configurable. If such changes occur after recognition, do not
certify current preservation across the changed basis. No dividend reinvestment
or synthetic adjustment is used to manufacture an upward gap. This conservative
approach can miss legitimate setups, especially newly listed or restructured stocks.
Missing action records and retrospectively revised Yahoo history remain limitations.

## Cache, UI and future backtesting

The existing universe cache is 24 hours; downloaded one-year prices/actions are
cached for one hour. The scan snapshot retains a broad event set so score, size,
volume and status filters never redownload/recompute historical patterns. Changing
lookback, gap definition or association window requires pressing the scan button;
unchanged cached prices are reused. Default UI filters are 1%, Bull Flag Score 60,
volume >=1.2, and both unfilled states. The default Gap Score minimum is 0.

Charts reuse candles, MA20/60 and regression lines, mark the historical breakout,
and shade the original gap from formation to latest session. Gap boundaries,
fill percentage, fill date, remaining size and current distance are shown separately.

Events include recognition `signal_date/index`, signal close and ATR, flag swing
low, and original pattern fields. `to_backtest_signal` produces an input for the
existing execution engine; it rejects gaps already filled when recognized. It
does **not** use current fill status or current Gap Score for entry selection.
`gap_score_at_signal` is stored separately. To backtest the strategy, generate all
historical events (including those later filled); using only today's unfilled
survivors would introduce look-ahead/selection bias. No duplicate RR/MFE/MAE engine
was added. For ±day associations, entry can be no earlier than the next open after
both facts are known. The current scanner itself is not a performance backtest.

## Test and validation commands

```powershell
python -m unittest tests.test_bull_flag_gap tests.test_bull_flag_gap_panel -v
python -m unittest discover -s tests -v
python -m src.gap_scan_cli
python -m src.gap_scan_cli --full --output validation/bull_flag_gap_full
```

The default CLI first scans the same specified 20-stock TWSE/TPEx validation sample
used for the prior backtest. The 2026-09-25 sample run processed all 20 successfully,
with no download errors and zero qualifying events for the 20-session window ending
2026-09-24. This is an actual empty result, not evidence about strategy profitability.

The full-universe report is written separately. `validation.json` records universe
coverage, errors, settings, market date and audits; CSVs contain all events, selected
candidates and official sample membership. Raw histories are saved only for event
stocks. Each returned candidate is rechecked against its source gap/low path and a
historical prefix ending on the breakout date. Synthetic tests cover both gap modes,
all three statuses, exact boundaries, multiple real flags, lookback edges, missing
sessions, actions, volume, future-data invariance and backtest-adapter compatibility.

Current-universe survivorship bias remains. Daily OHLC cannot establish exact
intraday event timing for OPEN_GAP beyond the observed opening price and subsequent
daily low. Exchange price limits, liquidity, Yahoo omissions, delayed prices and
corporate-action revisions can affect results. Check the displayed market date and
coverage/errors before interpreting an empty scan.
