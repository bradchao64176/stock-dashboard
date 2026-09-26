# 台股下降旗形選股

Extends the existing `app.py` using Streamlit's automatic `pages/` navigation.
Existing charts, PChome services, news collection, and AI analysis are unchanged.

## Run

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open **台股下降旗形選股** in the sidebar, choose the download market, and click
**更新資料並掃描**. The first full-market run can take several minutes. Changing
filters or selecting a candidate never downloads or analyzes the market again.
Use **重新下載** and submit to invalidate this scanner's caches. Refresh replaces
the session's snapshot; a missing official universe leaves the old snapshot intact.

No new packages are required: pandas (and its NumPy dependency), requests,
yfinance, Streamlit and Plotly are already installed through `requirements.txt`.
If this Windows environment reports an SSL key-log permission error, clear its
inherited setting for the current shell before launching: `$env:SSLKEYLOGFILE=''`.

## Data and architecture

- `services/taiwan_universe.py`: official [TWSE OpenAPI](https://openapi.twse.com.tw/)
  `/v1/opendata/t187ap03_L` and [TPEx OpenAPI](https://www.tpex.org.tw/openapi/)
  `/openapi/v1/mopsfin_t187ap03_O`. Company-roster membership plus four-digit
  nonzero codes excludes ETFs, ETNs, warrants and preferred-share suffixes.
  The `91` depositary-receipt prefix is also excluded. The security predicate is
  replaceable; this is deliberately conservative and not a general securities master.
  Partial market failures are shown explicitly, never replaced with example stocks.
- `services/yahoo_history.py`: one year of daily raw OHLC, Adj Close and Volume,
  40 symbols per batch, four yfinance threads, two failed-symbol retries with backoff.
  [yfinance download](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
  is called with `auto_adjust=False`. Its batch interface still uses per-symbol
  requests internally; it is not a single HTTP request for the entire market.
  Both MultiIndex orientations and single-ticker frames are supported.
- `src/bull_flag_config.py`: immutable detection thresholds and scoring settings.
- `src/bull_flag.py`: validation, indicators, regression, scores, scan summaries,
  and filter-before-ranking of alternative flag windows.
- `src/bull_flag_panel.py`: 24-hour universe cache, one-hour history cache, session
  scan snapshot, filters, tables, charts, CSV, and read-only existing News Score.
- `pages/1_台股下降旗形選股.py`: independently accessible page; opening it does not
  execute the main dashboard's automatic single-stock news collection.
- `tests/test_bull_flag.py`, `tests/test_bull_flag_panel.py`: deterministic algorithm,
  download/universe adapter, news lookup, and Streamlit interaction tests.

## Detection and scoring

At least 120 valid trading observations are required. Invalid dates, duplicate
dates, missing/non-finite prices or volume, invalid OHLC ranges, nonpositive prices,
negative volume and no latest trading volume cause a logged skip. All-null padding
from Yahoo batch alignment is removed. Dates are sorted; partial rows are not filled.

Before computing indicators, historical OHLC is adjusted using Adj Close / Close,
normalized to the latest quote. Thus displayed latest prices remain raw TWD, while
past candles and moving averages share a consistent corporate-action-adjusted basis.
Volume remains Yahoo-reported shares. MA5/10/20/60, volume MA5/20 and 5/10/20-day
returns are computed independently of news.

Latest close must exceed MA20, and MA20 must exceed MA60. A 20-observation pole
(configurable 10–20 in the UI) must gain at least 15%, ending at its highest high.
Return is from the first pole close to that high. The preceding 5–15 flag bars,
excluding the latest holdout bar, must have descending high and low regressions,
each with R² >= 0.35, positive channel width and relative slope difference <= 0.60.
Relative difference is `abs(high_slope-low_slope)/max(abs(slopes))`; slopes are
TWD per trading observation. All these thresholds are configurable.

`retracement = (pole_high - lowest_flag_low) / (pole_high - pole_start_close)`
must be <= 50%, including the latest bar's low. `pullback_pct` is separately
`lowest_flag_low/pole_high - 1`, a negative fraction. Latest close below projected
support fails. Yesterday's close must be at/below yesterday's regression resistance.

The latest close above projected resistance with volume > 1.2 times the **preceding
20 bars'** mean volume is BREAKOUT. The holdout is excluded from both the resistance
fit and volume baseline. `Volume_MA20` itself remains the conventional inclusive
moving average; `breakout_volume_baseline` records the separate pre-holdout baseline.
An upside cross without volume confirmation remains FORMING, explicitly labeled
待量確認. A stock can have several valid window lengths; filters are applied before
selecting its highest-scoring window. Results contain one row per ticker.

Each component is clipped to its configured maximum:

| Component | Maximum | Quality fraction |
| --- | ---: | --- |
| Uptrend | 20 | (MA20/MA60 − 1) / 0.10 |
| Flagpole | 20 | pole return / 0.30 |
| Descending flag | 20 | mean of slope similarity and mean R² |
| Pullback | 15 | 1 − retracement / maximum retracement |
| Volume contraction | 15 | (1 − flag/pole volume ratio) / 0.50 |
| Breakout | 10 | 1 for volume-confirmed breakout, otherwise 0 |

Both maxima and quality denominators live in `BullFlagConfig` / `ScoreWeights`.
Defaults: 80+ strong, 70–79 watchlist, 60–69 weak, below 60 hidden. Forming patterns
can score up to 90. Configuration rejects invalid ranges and weights not totaling 100.
Table percentages are percent points; exported `*_pct` fields are fractional returns.

News Score uses the latest stored analysis per article/stock, across up to 20 latest
articles, matching the existing PChome formula: `(importance-weighted sentiment + 1)
* 50`. Missing data stays missing. No news download or model inference is triggered;
scores are captured at scan time and never combined with Bull Flag Score.

## Verification

```powershell
python -m unittest tests.test_bull_flag tests.test_bull_flag_panel -v
python -m unittest discover -s tests -v
```

Tests cover forming/breakout, holdout regression, unconfirmed volume, no flag,
downtrend, sideways, deep pullbacks, missing/invalid/short data, volume contraction,
nonparallel channels, corporate actions, errors, both official schemas, batch retries,
unfinished sessions, independent news scoring and UI filtering without redownloads.

## Limitations

- This is a transparent heuristic, not a backtested probability or return forecast.
- Daily bars on the current Taipei date are excluded before 14:00; Yahoo may publish
  late, and halted stocks can have stale data. Always check `price_date` and scan time.
- Historical windows use current company membership; there is no delisted universe
  or point-in-time backtest support. New listings with insufficient history are skipped.
- Yahoo rate limits and missing symbols remain possible. Errors and validation skips
  are separate; successfully analyzed includes stocks without a pattern. Candidate
  summary counts use each stock's best pattern before display filters.
- Caches are in the Streamlit process, not a durable historical warehouse. A new
  server process downloads again. Concurrent users can still increase provider load.
- The initial UI can tighten the 15% pole/50% retracement/5–15-day defaults without
  recalculation; widening the search requires changing config and running a new scan.
- Ordinary-share filtering is conservative. Four-digit TDR codes starting 91 and
  unusual non-four-digit issuers are omitted; other security types need explicit rules.
