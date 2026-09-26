# Cached full-universe Impulse MACD validation

Latest price session: **2026-09-24**. Official-universe snapshot and existing SQLite
OHLCV reused; this run did not obtain a fresh live-market universe or price download.

| Measure | Result |
|---|---:|
| Universe / cached histories | 1,978 |
| Successfully analyzed | 1,757 |
| Skipped: latest data or warmup invalid | 221 |
| Distinct candidates, latest 5 sessions | 432 |
| TWSE candidates | 253 |
| TPEx candidates | 179 |
| Crosses on September 24 | 52 |
| Recent crossover events checked | 433 |
| Prefix-only checks passed | 433 |

Settings: SMMA/ZLEMA length 34, signal SMA 9; lookback 5 sessions (ages 0–4).
Positive-zone, MA and current histogram confirmation filters disabled.

Every recorded event was recomputed from history ending at its crossover date.
The audit checked MACD > Signal, previous MACD <= previous Signal, and matching
event MACD. `validation.json` records individual checks; `events.csv` retains all
events, including multiple events for one stock. `candidates.csv` keeps the latest
event per stock. `issues.csv` lists excluded tickers.

These checks validate detection timing, not returns, trade execution or profitability.
Raw-price corporate actions, finite-history EMA seeding and vendor omissions remain
limitations documented in `IMPULSE_MACD.md`.
