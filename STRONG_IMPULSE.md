# Strong Golden Cross preset

Open the existing Impulse MACD page and select **Strong Golden Cross**.
The strict preset requires every condition: actual crossover age <= 5 sessions,
crossover MACD > 0, current Close > MA20 > MA60, current five-session MA20 slope
> 0, cross-day Volume / rolling 20-session Volume >= 1.5, and latest revenue
YoY > 0.10. The volume average includes the evaluated day. Thresholds, volume
timing, freshness and positive cross-day return confirmation are configurable.

The advanced presets use the newly requested inclusive age <= N. The original
pure preset retains its existing latest-N-sessions interpretation. Both support
today-only age 0. Current trend values are never substituted for crossover zone
or crossover volume. The strong-only toggle can be disabled to inspect failures.
Missing revenue is UNKNOWN; revenue more than two calendar months old defaults
to STALE. Neither qualifies. A score cannot override any mandatory condition.

## Revenue and cache

Official sources:
- https://openapi.twse.com.tw/v1/opendata/t187ap05_L
- https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O

`services/monthly_revenue.py` calculates (current revenue - prior-year revenue) /
prior-year revenue, without rounding before the strict >10% comparison. Revenue
amounts retain the source's units. A missing or nonpositive prior-year base yields
unknown growth, not zero. The report month is displayed with growth.

The existing `data/unfilled_gap_prices.db` gains:
- `monthly_revenue`: latest observed version per (stock_code,year_month).
- `monthly_revenue_versions`: versioned economic values and availability timestamps.
- `revenue_fetches`: endpoint refresh timestamps, default 24-hour TTL.

The source's 出表日期 is retained as a report date, **not** treated as an individual
announcement timestamp. `revenue_publish_date` remains NULL when unavailable.
First observation in this system is the conservative availability bound. Corrections
are retained as new versions, including corrections back to previously seen values.
Revenue obtained today cannot qualify signals from earlier dates.

## Score (0–100)

Each component is separately returned: actual cross 20; positive zone 10; current
trend conditions 20 equally divided; volume 20 linearly from ratio 1 to 3; revenue
growth 20 linearly from 0% to 50%; cross-day return 10 linearly from 0% to 5%.
Components are capped. Ratio >3 produces EXTREME_VOLUME rather than an extra bonus.
These weights are explanatory heuristics, not empirically optimized parameters.

## Existing-engine backtest integration

`backtesting/impulse.py` compares A pure, B positive zone, C MA alignment, D rising
MA20, E volume expansion, F revenue growth through `execute_backtest`. The existing
next-open entry, ATR or percentage stop, costs, same-bar policy, gap fills and
overlap handling are reused. RR targets 1/1.5/2/2.5/3 and horizons 5/10/20/30 are
independent scenarios. Forward returns are separate gross next-open-to-horizon-close
research observations and include overlapping signals; they are not trade returns.

Historical trend/current volume refer to the signal day, never the end of the
dataset. Revenue lookup uses versions available by signal-day 14:00 Taipei time.
The initial current-month download provides no coverage for earlier historical
signals: F may have zero eligible observations and undefined performance. This
must not be interpreted as evidence for or against revenue filtering. Historical
announcement/version archives are needed for a meaningful historical F comparison.
The current-listing universe has survivorship bias. Raw Yahoo prices and daily
OHLC execution limitations remain unchanged. Research drawdown is the existing
aggregate trade-P&L measure, not a capital-constrained portfolio simulation.

## Files and commands

Created: `services/monthly_revenue.py`, `src/strong_impulse.py`,
`backtesting/impulse.py`, `tests/test_strong_impulse.py`, this document.
Modified: `src/impulse_macd.py` (volume/return/ATR columns), `src/impulse_panel.py`
(presets, diagnostics, volume chart, comparison UI), `src/impulse_cli.py` (strong
scan and optional comparison). No dependencies added.

```powershell
python -m streamlit run app.py
python -m src.impulse_cli --strong --limit 0 --output validation/strong_impulse_full
python -m unittest discover -s tests -q
```

Optional research uses `--compare`; normal full-market selection does not run a
backtest. The A–F comparison can also be started explicitly from the page.
129 automated tests pass, including strict boundary values, unknown/stale revenue,
revision timing, future-data invariance, volume timing modes and preset UI behavior.

Full-market execution on 2026-09-26 returned 28 strict matches (18 TWSE, 10 TPEx)
from 1,978 stocks; 1,757 analyzed and 221 skipped. Price data as of 2026-09-24,
revenue period 2026-08. Every selected row passed all mandatory numeric checks.
See `validation/strong_impulse_full/review.md` and `candidates.csv`.
The user requested full-market selection instead of the proposed sample/backtest
run; no actual A–F performance study was executed in this session.
