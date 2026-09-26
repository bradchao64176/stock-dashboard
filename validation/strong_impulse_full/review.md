# Strong Golden Cross — full TWSE/TPEx scan

Scan run: 2026-09-26. Latest observed completed price session: **2026-09-24**.
Monthly revenue period for all selected stocks: **2026-08**. Official revenue
was retrieved and first observed on 2026-09-26; these are current screening
results, not historical signal-day revenue selections or backtest results.

- Universe: 1,978 current TWSE/TPEx common stocks.
- Histories available: 1,978; analyzed: 1,757; skipped: 221.
- Recent crossover stocks before strict filtering: 500.
- Strict matches: **28** (18 TWSE, 10 TPEx).
- Universe/revenue/download errors: none reported.
- All recorded crossovers passed prefix-only recalculation.
- All 28 selected rows independently passed numeric AND-condition checks.

Required conditions: crossover age 0–5 inclusive; crossover-day MACD > 0;
current Close > MA20 > MA60; normalized MA20 five-session slope > 0;
crossover-day Volume / Volume_MA20 >= 1.5 (average includes crossover day);
latest available revenue YoY > 10%, with revenue freshness at most two months.

Matched stocks in score order:
3296 勝德, 1727 中華化, 6651 全宇昕, 3653 健策, 6902 GOGOLOOK,
2434 統懋, 2466 冠西電, 6526 達發, 3066 李洲, 6204 艾華,
3219 倚強科, 6508 惠光, 2360 致茂, 6894 衛司特, 6147 頎邦,
6257 矽格, 6278 台表科, 5864 致和證, 3434 哲固, 4771 望隼,
6840 東研信超, 6005 群益證, 5285 界霖, 3189 景碩, 2481 強茂,
2477 美隆電, 2107 厚生, 1437 勤益控.

`candidates.csv` contains the full table, source dates, cross/current values,
condition flags and score components. `events.csv` includes rejected crossovers
with failed-condition reasons; `issues.csv` lists skipped stocks. `validation.json`
contains individual prefix audits. Scores are heuristics, not profitability estimates.

This run intentionally did not execute the optional A–F backtest comparison.
