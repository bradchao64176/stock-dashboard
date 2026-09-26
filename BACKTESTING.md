# Bull Flag Backtesting Engine / 下降旗形突破回測系統

This feature extends the existing scanner. No new dependencies are required.
The main dashboard, scanner, news collection, and separate News Score remain available.

## Run

```powershell
python -m streamlit run app.py
```

Open **下降旗形策略回測** in the left menu. Set parameters and press **執行回測**.
The default UI research period is five years and the initial stock limit is 20,
selected by official code order; specify codes to choose a sample. Set the limit
to 0 for all common stocks in the selected market. Full-market runs may take minutes
and substantial memory. Changing result controls never triggers data acquisition.

Reproduce the small validation run:

```powershell
python -m backtesting.cli --years 2 --end 2026-09-25
```

CLI supports `--codes 2330,5483,...`, `--years 1|2|3|5|10`, `--end YYYY-MM-DD`,
`--refresh`, and `--output PATH`. It defaults to the documented 20-stock sample,
not the whole market. On this Windows environment, if inherited SSL logging raises
a permission error, set `$env:SSLKEYLOGFILE=''` in the launch shell.

```powershell
python -m unittest discover -s tests -v
python -m unittest tests.test_backtest_execution tests.test_backtest_engine tests.test_backtest_metrics tests.test_backtest_storage_ui -v
```

## Files and layers

| New file | Responsibility |
| --- | --- |
| `backtesting/__init__.py` | Package |
| `backtesting/config.py` | Immutable detector/execution/cost/sizing settings |
| `backtesting/signals.py` | Causal preparation, ATR, existing detector on historical prefixes |
| `backtesting/execution.py` | Stops, sequential fills, costs, outcome and excursions |
| `backtesting/engine.py` | Signal generation and independent RR/horizon position ledgers |
| `backtesting/metrics.py` | Net-R statistics, equity/drawdown and characteristic groups |
| `backtesting/cli.py` | Small-sample runner, prefix audit and CSV/JSON export |
| `services/backtest_history.py` | SQLite exact-range price cache using existing Yahoo service |
| `src/backtest_panel.py` | Controls, metrics, charts, inspection and CSV exports |
| `pages/2_下降旗形策略回測.py` | Streamlit page |
| `tests/test_backtest_execution.py` | Deterministic trade fills and risk tests |
| `tests/test_backtest_engine.py` | Detector integration, future-data invariance, overlaps, date split |
| `tests/test_backtest_metrics.py` | Expectancy, denominators, profit factor and drawdown |
| `tests/test_backtest_storage_ui.py` | Date-range forwarding, local cache, no-download UI reruns |
| `BACKTESTING.md` | Rules and usage |
| `validation/bull_flag_backtest/*` | Actual sample CSVs, metadata and trade review |

Modified existing files:

- `services/yahoo_history.py`: optional period/start/end; default scanner download
  remains one year. Explicit dates use yfinance's inclusive start/exclusive end.
- `src/bull_flag.py`: optional `adjust_prices=False` on existing indicator function;
  scanner's existing adjusted behavior is unchanged.
- `src/navigation.py`: add backtest page, retaining **stock-dashboard Apps** label.

Storage lives in `data/backtest_prices.db`, separate from the news SQLite database.
JSON price snapshots are keyed by ticker/start/end and cached for 24 hours. Failures
are not persisted as successful history. `--refresh`/the UI refresh option replaces
only requested ranges. Signal generation has its own Streamlit cache; execution
uses the saved signal set; all chart/filter/export operations use the session result.
No new cache is loaded via pickle from disk.

## Historical signal definition

Reuse `detect_patterns` and the scanner's scoring model; no parallel detector.
Require `Close > MA20 > MA60` and positive five-observation MA20 slope at signal T.
The default pole is 20 observations with at least 15% first-close-to-final-high rise.
The pole must end at its highest high. Fit high and low regressions over the preceding
5–15 flag observations, excluding signal T. Both slopes must be negative, relative
slope difference <= 0.60, R² >= 0.35 and channel width positive. Retracement <= 50%
of the pole advance includes T's low. The latest close cannot be below flag support.

Signal close must exceed projected resistance, with the preceding close still below
the preceding resistance. Volume confirmation defaults to >1.2 times the **previous
20 observations'** mean; T is excluded from this baseline. This differs deliberately
from inclusive `Volume_MA20`, which remains available separately. Volume confirmation
can be disabled; unconfirmed scanner patterns then qualify if they meet the score
threshold, without being awarded the scanner's confirmed-breakout score component.
Volume contraction is a score preference by default, or an optional hard filter.
The highest-scoring qualifying window produces at most one signal per ticker/day.

## Time and data integrity

- Indicators use only backward rolling windows on Yahoo OHLC. Historical backtests
  **do not apply future-anchored Adj Close factors**. The detector receives a slice
  ending at T; no future regression, high, low, return or ATR enters the signal.
- Yahoo's OHLC may itself be retrospectively split-adjusted/revised. This is not
  archival point-in-time data. Dividends/cash distributions are not credited and
  ex-dividend price drops can affect stops; results are price-strategy research.
- A 240-calendar-day warmup is acquired before the requested signal start. At least
  120 consecutive valid observations are required. OHLCV defects/zero volume reset
  warmup without erasing earlier signals. Duplicated dates reject the ticker.
  Missing rows are not interpolated; the provider may omit dates entirely, and the
  engine cannot distinguish omitted exchange sessions from holidays/suspensions.
- Entries occur at the **next available daily open**, never at T's closing price.
  Entry day is holding day 1, and its high/low may trigger a same-day exit.
- Entries with missing data, nonpositive risk, nonpositive stop, or zero shares are
  skipped and recorded. Missing/invalid bars after entry produce CENSORED results.
- Evaluation never looks beyond its end date. Unresolved end-of-data positions are
  CENSORED, not fabricated TIMEOUT exits. An early stop/target can still resolve.
- Signals are shared, but overlap state is independent for each RR/horizon/segment.
  By default a ticker cannot enter while its prior trade is active, including on
  its prior exit day. A later signal known at that close can enter the following day.
  Censored positions block reentry through their nominal holding horizon.

## Stops, targets and execution

`entry_price` is the observed next open; `risk_per_share = entry_price - stop_price`.

- **FLAG_LOW (default):** minimum Low over the detected flag, excluding signal T.
- **ATR:** entry minus the signal day's ATR(14) × 1.5. ATR is simple mean true range,
  not Wilder smoothing; period/multiplier are configurable.
- **PERCENTAGE:** entry × (1 − stop_pct), default 5%, optional research method.

Targets are entry + RR × risk; default RR values are 1, 1.5, 2, 2.5, 3. Holding periods
are 5, 10, 20, 30 observations. All can be selected independently in the UI.

Opening auction is evaluated before the candle range. Open <= stop exits at open
(possibly worse than −1R); open >= target exits at open (possibly better than +RR).
Otherwise, the first subsequent daily touch exits at the threshold. If both levels
are touched on that candle: CONSERVATIVE assumes stop first, OPTIMISTIC target first,
EXCLUDE records AMBIGUOUS with no realized P&L. Every dual-touch case is flagged.
No intraday sequence is inferred. TIMEOUT exits at the final holding day's close.
Slippage is applied to executable fills separately; threshold-trigger exits are a
market-on-trigger approximation, not a guarantee of an exchange limit-order fill.

## Costs and sizing

Editable default research assumptions:

| Item | Default |
| --- | ---: |
| Brokerage | 0.1425% each side |
| Minimum commission | TWD 20 each side |
| Transaction tax | 0.3% of sale value |
| Slippage | 0.05% each side |
| Starting capital | TWD 1,000,000 |
| Fixed initial-capital risk budget | 1% per independent trade |

Commission schedules/discounts/minima depend on the broker; the defaults are not
claims about a particular account. [TWSE commission rules](https://twse-regulation.twse.com.tw/eng/en/law/DOC01.aspx?FLCODE=FL007304&FLNO=94)
allow broker-set schedules. The [TWSE investment guide](https://www.twse.com.tw/en/about/company/guide.html)
describes the standard stock sale tax and qualifying day-trade concession. This
engine uniformly applies the entered tax rate, without historical eligibility rules
or automatic same-day concessions. Set costs off for pure zero-cost research.

Buy fill = entry open × (1 + slippage); sell fill = exit reference × (1 − slippage).
Fees use these fill notionals and minimum fees per side. Tax uses sale fill notional.
Gross P&L uses reference opens/thresholds before all costs; net P&L deducts slippage,
fees and tax. `gross_return_pct`/`net_return_pct` divide by reference entry notional.
`gross_R`/`result_R` divide by reference initial risk × shares. Costs may turn a
target WIN into a net loss; WIN/LOSS denote barriers, not the sign of net P&L.

Sizing is integer shares: floor(initial capital × risk budget / R), or fixed shares.
These are **independent-trade research curves**, with no aggregate capital/exposure
limit, mark-to-market valuation, cash interest, compounding, lot/tick-size rounding,
or liquidity constraint. Max drawdown is realized-exit drawdown, not portfolio risk.

## Metrics and charts

`Total Signals` precedes entry/overlap exclusions. `Total Trades` counts entries,
including AMBIGUOUS/CENSORED. `evaluated_trades` counts WIN + LOSS + TIMEOUT.

- Main win rate = WIN / evaluated; loss and timeout rates use the same denominator.
- `decided_win_rate` excludes timeouts and answers a different conditional question.
- `hit_rate_all_entries` includes censored/excluded trades in the denominator and
  is an observed lower bound, not an unbiased estimator.
- **Expectancy = mean actual net result_R**, including positive/negative timeouts.
  Profit factor = positive net R sum / absolute negative net R sum. With gains and
  no losses it is infinity; with no realized data it is N/A, not zero.
- Break-even = 1/(1+RR), before fees/gaps/timeouts. It is only a theoretical benchmark.
- Streaks use chronological exit ordering, then ticker/signal date as tie breakers;
  simultaneous trades do not have a uniquely meaningful ordering.
- Equity starts at initial capital, groups realized P&L by exit date, and includes
  the starting baseline in peak/drawdown calculations. Cumulative R is also shown.

MFE/MAE percentages and R are **daily-bar excursion bounds**, from entry through exit.
On a threshold/timeout exit day, full candle high/low are included and may have occurred
after the fill. On an opening-gap exit, only open is included for that day. Censored
records contain observed-to-date bounds. These are not exact intraday excursions.
The UI labels this limitation beside histograms/scatter plots and exposes the basis
in trade records. Parameter grouping uses the selected scenario, not pooled repeated
simulations of the same signal: score, market, pole gain, retracement, flag volume,
and breakout volume are supported.

## Training / out-of-sample structure

The optional fixed split date separates TRAIN and OOS signals. Training trades are
cut off before OOS begins and censored if unresolved; pre-test observations may supply
OOS indicator warmup. Parameters are supplied manually and are never optimized by
the engine. There is no rolling walk-forward optimizer. Separate `build_signal_set`,
`execute_backtest` and immutable config support future rolling folds. Repeated manual
parameter selection after inspecting OOS results contaminates that holdout.

## Actual validation and remaining limits

See [validation review](validation/bull_flag_backtest/review.md) and exported CSV/JSON
for the actual 20-stock, two-year sample, assumptions and inspected WIN/LOSS/TIMEOUT
trades. This sample is not representative of the whole market and was not optimized.
The current company universe omits delisted firms: **survivorship bias remains**.

Daily Yahoo prices cannot model intraday ordering, partial fills, price-limit locks,
execution queues or suspensions reliably. Missing data can exclude trades and alter
sample composition. Fees are constant assumptions, not a historical brokerage ledger.
Raw Yahoo OHLC means scanner and backtest may differ around dividends. No full-market
10-year scalability benchmark or portfolio backtest has been performed. Refreshing
Yahoo can revise historical results; exported metadata records settings and run time.
