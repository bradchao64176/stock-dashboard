# Full-market Bull Flag Gap Breakout scan

Latest observed session: 2026-09-24. Official current universe: 1,978 common stocks.
Downloaded all 1,978; analyzed 1,939; skipped 39 due to stale/invalid latest bars or
insufficient history. No official-list or download failures were reported.

With the default 20-session lookback, same-day full gap >=1%, valid historical Bull
Flag with score >=60, positive MA20 slope and breakout volume ratio >=1.2, the scan
found **zero qualifying events and zero candidates**. Empty exports reflect the
actual result; no example stocks were inserted.

This stricter Bull Flag gap strategy remains independent from the subsequently added
general **Unfilled Bullish Gap Scanner**, whose rules do not require a Bull Flag.
See `validation.json` for settings, coverage and skipped-stock reasons.
