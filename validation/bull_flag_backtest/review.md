# Validation review — 2026-09-25

Actual Yahoo data, current official TWSE/TPEx membership; 20 specified stocks,
signal dates 2024-09-25 through 2026-09-25, plus indicator warmup. See `validation.json`
for the exact universe, acquisition/run timestamp, parameters and five prefix audits.
All 20 histories were downloaded and processed; no source/download errors occurred.
Individual invalid/zero-volume rows reset signal warmup and are logged in that JSON.

There were **7 signals**. One was skipped because its next open made flag-low risk
invalid. Each 20-day RR scenario entered 6 trades. These are a very small selected
sample, not evidence of a Taiwan-wide success rate or future profitability.

Defaults: score >=60, pole >=15%, confirmed breakout volume >1.2×, flag-low stop,
conservative same-bar policy, no same-stock overlap. Costs: 0.1425% brokerage each
side (TWD 20 minimum), 0.3% sale tax, 0.05% slippage each side. Risk sizing uses
1% of TWD 1m initial capital per independent trade.

| RR | Entered | Evaluated | Wins | Losses | Timeouts | Censored | Win rate | Break-even | Net expectancy | Net-R PF | Realized max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1:1 | 6 | 6 | 5 | 1 | 0 | 0 | 83.33% | 50.00% | +0.6585R | 4.6826 | 1.0231% |
| 1:1.5 | 6 | 6 | 4 | 1 | 1 | 0 | 66.67% | 40.00% | +0.8830R | 5.9380 | 1.0103% |
| 1:2 | 6 | 6 | 4 | 1 | 1 | 0 | 66.67% | 33.33% | +1.1531R | 7.4490 | 0.9996% |
| 1:2.5 | 6 | 5 | 3 | 1 | 1 | 1 | 60.00% | 28.57% | +1.2925R | 7.0239 | 0.9858% |
| 1:3 | 6 | 5 | 2 | 1 | 2 | 1 | 40.00% | 25.00% | +1.1134R | 6.1892 | 0.9941% |

Win-rate denominator includes TIMEOUT and excludes unresolved CENSORED trades. The
higher-R scenarios have different evaluated samples; this table cannot establish
an optimal target. Drawdown is on realized independent-trade P&L, not a constrained
portfolio's marked-to-market value. Full precision/all horizons: `rr_comparison.csv`.

## Manual OHLC review

Reviewed these cached source rows against the 1:2 / 20-day records:

- **2303.TW WIN:** signal 2026-04-30 close 77.30; next available open on 2026-05-04
  is 80.00. Flag stop 70.699997, target 98.600006. May 4–6 highs 82.40/85.20/91.40
  are below target and lows above stop. May 7 open 97.40 is below target; high 98.80
  crosses it, low 93.00 does not touch stop. Exit at target, holding 4 observations.
  MFE +2.0215R and MAE −0.0645R are daily-bar bounds; net result +1.9312R.
- **2454.TW LOSS:** signal 2026-06-09 close 4475; next open 2026-06-10 is 4315.
  Stop 3935 and target 5075. Entry-day high/low 4520/4120 touch neither barrier.
  June 11 open 4085 is above stop, low 3880 crosses stop, high 4150 is below target.
  Exit 3935, holding 2 days. MFE +0.5395R, MAE −1.1447R (exit-day range extends
  below the executed stop), net result −1.0728R.
- **2308.TW TIMEOUT:** signal 2026-02-11 close 1260; next available daily row is
  February 23 open 1320, not a fabricated calendar-day entry. Stop 1115, target 1730.
  All 20 holding observations through March 23 stay within these barriers; maximum
  high 1530 and minimum low 1195. Exit at March 23 close 1410, net +0.3928R,
  MFE +1.0244R, MAE −0.6098R.

The CLI also reconstructed five signals using only raw history ending on each signal
date and checked their score, next-open entry, flag low, risk and target. No future
candles were needed to reproduce them. Unit tests separately cover all same-bar
policies, gap exits, costs, all RR targets, missing data, overlaps and future-data
perturbation. This validates implementation behavior, not economic robustness.
