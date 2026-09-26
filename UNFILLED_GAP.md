# 多方未回補缺口選股 / Unfilled Bullish Gap Scanner

This is a separate strategy without a mandatory Bull Flag. The original Bull Flag
Scanner, Bull Flag Gap Breakout scanner, News Score and Backtesting Engine remain
available. Its goal is to screen current bullish trends with a recent preserved gap.

## Run and configure

```powershell
python -m streamlit run app.py
```

Choose **多方未回補缺口選股** in the sidebar. The default stock count is 0 (all current
TWSE/TPEx common stocks). Controls include market, gap lookback/type/size, return
lookback/threshold, five independent MA rules, slope lookback, gap-day/current/both
evaluation, optional MA distance bounds, optional volume confirmation and untouched
only. Press **執行未回補缺口選股** after changing strategy parameters. Prices are reused
from SQLite; status filtering and trade inspection never trigger downloads.

Run small-sample validation, followed by all stocks if requested:

```powershell
python -m src.unfilled_gap_cli
python -m src.unfilled_gap_cli --full
python -m unittest tests.test_unfilled_gap tests.test_unfilled_gap_panel -v
python -m unittest discover -s tests -v
```

The CLI's `--full` mode validates the 20-stock sample first, then processes the whole
official universe. `--refresh` refreshes prices. In this Windows environment, clear
an inherited SSL key-log setting if it prevents requests: `$env:SSLKEYLOGFILE=''`.

## Defaults

| Parameter | Default |
| --- | --- |
| Gap lookback | Last 20 observed trading sessions, including latest (ages 0–19) |
| Recent return | Current close / close 20 sessions earlier − 1 >= 10% |
| Gap | FULL_GAP: Low[t] > High[t−1] |
| Minimum gap | 1% of previous high |
| Close > MA20 | Required |
| MA20 > MA60 | Required |
| MA20 rising | Required |
| MA60 rising | Optional, off |
| Full alignment | Close > MA5 > MA10 > MA20 > MA60; optional, off |
| Slope lookback | 5 sessions |
| Trend evaluation | GAP_DAY_AND_CURRENT |
| MA distance filter | Optional, off; minimum 0, maximum None |
| Gap preservation | UNTOUCHED or PARTIALLY_FILLED |
| Gap-day volume confirmation | Optional, off; threshold 1.2 if enabled |

The distance filter has an explicit enable switch so disabling the MA20>MA60 rule
does not silently leave the same restriction active through a zero distance bound.
The stronger full-alignment rule also requires close above MA5, as specified.

## Historical timing

Indicators reuse `prepare_history` and the existing rolling MA5/10/20/60 calculation
on Yahoo OHLC. No Adj Close adjustment anchored at a future date is applied.

`ma20_slope_pct = MA20[t] / MA20[t−L] − 1`, likewise for MA60. L is configurable
(1–60 sessions). The relevant window must be continuous and valid; after a missing
bar, slope/return comparisons cannot bridge the missing history. Slope is a period
percentage change, not a daily derivative or a regression coefficient.

Every event retains **two independent snapshots**, prefixed `gap_day_` and `current_`:
close, MA5/10/20/60, normalized MA20/MA60 slopes, return, MA distance, latest observed
golden-cross date/age, and Boolean rule results. No current values are substituted
for a historical gap-day condition.

- GAP_DAY tests only historical MA structure.
- CURRENT tests only latest MA structure.
- GAP_DAY_AND_CURRENT requires both.

The recent-return threshold always uses current return for the current scanner;
gap-day return is also recorded for a historical entry strategy. Golden cross means
prior MA20 <= MA60 and current MA20 > MA60. Unknown crosses before the dataset starts
are left missing; no cross is inferred merely because the first available MA20 is
above MA60. Cross history resets after missing data and is descriptive, not mandatory.

## Gaps and data integrity

Reuses the Bull Flag gap module's `gap_zone`, `fill_state`, observed-session calendar,
corporate-action guard and missing-date handling. The distinction among UNTOUCHED,
PARTIALLY_FILLED and FILLED is unchanged, including exact boundary-touch rules.
OPEN_GAP includes the formation day's low in fill tracking. First full-fill date,
remaining gap, lowest later price and data-completeness flags remain available.

All recent positive-gap events are retained independently of the selection rules,
so filters and future research can inspect rejected/filled events. The table picks
the newest qualifying unfilled gap per stock, then sorts by the separate score.
Incomplete post-gap data or subsequent corporate-action changes do not certify an
unfilled gap. The entire snapshot is labeled with the observed market date.

## Transparent Unfilled Gap Score

This score does not overwrite Bull Flag Score or Bull Flag Gap Breakout Score.
Component values are returned separately (`score_*`); all denominators and weights
are centralized in `UnfilledGapConfig` / `UnfilledScoreWeights`.

| Component | Points | Quality fraction, clipped to [0,1] |
| --- | ---: | --- |
| Trend quality | 20 | Mean of Close>MA20, MA20>MA60, MA20 slope/2%, MA60 slope/1%, MA distance/10% |
| Recent return | 20 | Current return / 30% |
| Gap size | 15 | Gap percentage / 5% |
| Gap preservation | 20 | 1 − fill fraction |
| Strength after gap | 10 | (Current close / gap-day close − 1) / 10% |
| Gap-day volume | 15 | Gap-day volume / prior 20-session mean / 3 |

Trend quality uses the selected evaluation date or the mean of gap-day/current
quality in BOTH mode. The historical `score_at_signal` uses gap-day inputs only:
current-at-that-time equals gap day, post-gap return is zero, and no subsequent fill
path is included. Scores describe rules; they are not estimated win probabilities.

## Backtesting compatibility and comparisons

`to_unfilled_backtest_signal` produces signals for the existing next-open execution
engine. It uses only gap-day MA/return/volume and the state known at gap close. It
never conditions entry on today's surviving gap, current MA values or current score.
The default mapped structural stop is the gap bottom, passed using the existing
engine's structural-stop field `flag_swing_low`; it is not a claim that a Bull Flag
exists. ATR and percentage stops remain supported by the execution configuration.

`compare_trend_variants(events, histories, base, execution)` exposes five historical
entry variants with identical non-MA rules: gap only, MA20>MA60, Close>MA20>MA60,
rising MA20, and full MA alignment. It returns the existing RR/horizon comparison
metrics (signals, wins, expectancy, profit factor, MFE/MAE, drawdown) plus per-signal
5/10/20/30-session gross forward close returns from next-open entry. Missing horizons
remain missing; forward returns are research outcomes, never entry inputs.

For historical testing, the caller must generate a complete historical event set,
including events that later filled; today's last-20-session candidates are not a
valid historical sample. At entry, 'current' is that historical decision date, so
Gap Day + today's persistence cannot be retrospectively imposed without look-ahead
bias. Testing persistence requires a separately defined delayed-entry decision.
The helper does not claim that adding MA conditions improves results and does not
optimize parameters. No new execution/stop/RR engine was introduced.

## Files and storage

Created: `src/unfilled_gap_config.py`, `src/unfilled_gap.py`, `src/unfilled_gap_panel.py`,
`src/unfilled_gap_cli.py`, `pages/4_多方未回補缺口選股.py`, `tests/test_unfilled_gap.py`,
`tests/test_unfilled_gap_panel.py`, this document and validation artifacts.

Modified: `src/navigation.py` adds the independent page;
`services/backtest_history.py` adds a separate actions-aware SQLite cache table.
The ordinary backtest cache remains separate and compatible. No new dependencies.
The new strategy's cache is `data/unfilled_gap_prices.db`; exact date ranges and
action-inclusive data are cached for 24 hours. UI and CLI share this cache.

Validation files: `validation/unfilled_gap_sample/` and `validation/unfilled_gap_full/`
contain `candidates.csv`, `events.csv`, `universe.csv` and `validation.json`. Each
returned stock is audited by rebuilding gap-day MAs from a truncated prefix and
checking current MA conditions, recent return, gap size, age and the low-price path.

## Limitations

Current TWSE/TPEx membership has survivorship bias; Yahoo data can be missing, stale,
retrospectively revised or split-adjusted. The calendar is inferred from positive-
volume dates across downloaded stocks, not an official exchange calendar service.
Actions and unusually large price discontinuities are handled conservatively and
can cause omissions. A full-market current scan does not establish historical
profitability. Historical comparison helpers are tested deterministically but a
full historical MA-variant performance study has not been run.
