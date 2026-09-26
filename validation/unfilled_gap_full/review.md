# Full-universe validation — MA-filtered unfilled gaps

Run date: 2026-09-26. Latest observed market session: **2026-09-24**.

- Official current ordinary-share universe: **1,978** (TWSE + TPEx).
- Downloaded: **1,978**, no reported universe or download errors.
- Analyzed: **1,940**. Skipped: **38** (33 missing/invalid latest session, 5 insufficient history).
- Recent positive gap events retained internally: **1,066**, including small, filled,
  incomplete and trend-rejected events. This is not the selected-stock count.
- Selected stocks: **39** — **25 TWSE**, **14 TPEx**.
- Preserved gaps: **26 UNTOUCHED**, **13 PARTIALLY_FILLED**.
- All **39** returned stocks passed separate historical/current/fill-path audits.

Defaults were unchanged: current 20-session return >=10%, FULL_GAP >=1%, last 20
sessions, Close>MA20>MA60 and positive 5-session MA20 slope on both gap day and current
day. MA60 rising, full MA alignment and volume confirmation were optional/off.
Neither Bull Flag detection nor a Bull Flag score threshold is required by this
independent strategy. All candidates' original gaps remained not completely filled.

The runner first processed its 20-stock validation sample: 20 downloaded/analyzed,
17 stored positive-gap events and 2 selected stocks (2454 and 2409). It then processed
the full universe using the same parameters, reusing those 20 downloaded histories.

## Highest scores (descriptive ranking)

| Code | Stock | Market | Gap date | 20-session return | Original gap | Fill depth | Score |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 6221 | 晉泰 | TPEx | 2026-09-15 | 48.39% | 9.96% | 1.96% | 95.83 |
| 5465 | 富驊 | TPEx | 2026-09-22 | 41.32% | 4.60% | 0.00% | 94.48 |
| 2033 | 佳大 | TWSE | 2026-09-18 | 57.60% | 2.11% | 0.00% | 89.38 |
| 6902 | GOGOLOOK | TWSE | 2026-09-22 | 38.98% | 4.19% | 0.00% | 88.18 |
| 3094 | 聯傑 | TWSE | 2026-09-18 | 42.52% | 2.97% | 0.00% | 86.11 |
| 2305 | 全友 | TWSE | 2026-09-17 | 113.58% | 6.88% | 0.00% | 85.88 |
| 1569 | 濱川 | TPEx | 2026-09-21 | 44.58% | 1.05% | 0.00% | 83.75 |
| 3219 | 倚強科 | TPEx | 2026-09-22 | 35.50% | 1.01% | 0.00% | 83.45 |
| 2444 | 兆勁 | TWSE | 2026-09-21 | 33.33% | 6.67% | 41.18% | 83.43 |
| 2221 | 大甲 | TPEx | 2026-09-22 | 119.84% | 5.36% | 0.00% | 83.04 |

Use `candidates.csv` for all 39 stocks and full precision; numeric *_pct fields in
CSV use fractions (0.10 = 10%). `events.csv` includes the separate gap-day/current
MA snapshots, score components, fill dates and golden-cross fields. `validation.json`
records exact settings, source coverage, skip reasons and the 39 candidate audits.

## Verification and interpretation

For each selected stock, the audit reloaded the source history, rebuilt the gap-day
indicators using a prefix ending on the gap date, and compared them with stored
event values. It also checked current MAs, normalized slopes, recent return >=10%,
gap size >=1%, event age <20 and every available subsequent low. Today's MA values
were not used to reconstruct a historical gap-day condition.

These are current scan results, not a historical strategy performance estimate.
The score is heuristic. Current-universe survivorship bias, provider revisions,
inferred trading calendars and conservative corporate-action exclusions remain.
The existing **Bull Flag Gap Breakout** strategy was scanned separately with its
stricter flag requirement and returned zero candidates; that result must not be
confused with the broader 39-stock unfilled-gap strategy.
