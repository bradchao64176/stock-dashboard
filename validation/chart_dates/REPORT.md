# Crosshair date-axis regression

## Reproduced root cause

The crosshair helper reassigned all Impulse traces to `x`, while the MACD zero
line retained `xref="x3 domain"` and the lower Y axes retained `x2`/`x3` anchors.
In headless Edge, Plotly.js removed the unused axis and coerced the zero line to
`xref="x"`. Its domain coordinates 0 and 1 became January 1, 1970 dates.
The reproduced rendered range was 1969-11-16 through 2030-09-27.

The candle, MA20, MA60, volume, volume MA20, MACD, signal, histogram and Golden
Cross trace coordinates were already recent trading dates. The problem was the
orphaned shape reference, not cached market data or scanner results.

## Repair

- Remap shape/annotation references and Y-axis anchors together with traces.
- Preserve `x domain` for the MACD zero line; remove unused axes without
  recreating them through `make_subplots`' original grid metadata.
- Normalize chart-only history copies, remove invalid/numeric dates, and sort.
- Validate date-coordinate traces, markers, shapes and annotations. Numeric
  epochs/indices are rejected; paper/domain coordinates remain numeric.
- Explicit date axis type, no hard-coded range. Crosshair does not set ranges.
- Keep unified hover, cursor spikes, all original traces and overlay values.

Files changed for this repair:
`src/chart_interaction.py`, `src/impulse_panel.py`, `src/bull_flag_panel.py`,
`src/bull_flag_gap_panel.py`, `src/unfilled_gap_panel.py`,
`src/backtest_panel.py`, `tests/test_chart_interaction.py`.

## Browser verification

The standalone before/after HTML fixtures use local Plotly.js and synthetic
data; no Yahoo request, database write, or LINE send occurs.

After repair, every full-length data trace spans **2026-04-01 to 2026-10-02**;
the Golden Cross marker is **2026-10-01**. The rendered zero line retains
`xref="x domain", x0=0, x1=1`. No 1970 date exists in rendered traces or shapes.

Rendered autorange is **2026-03-31 to 2026-10-13**, including Plotly's normal
candle/marker padding. Programmatic browser zoom to August–October, pan to
July–September, and autorange reset succeeded. Unified hover and horizontal/
vertical spikes remain enabled throughout. Physical mouse gestures were not
tested in this run.

## Automated verification

Tests cover real Impulse chart construction, every date trace, marker dates,
zero-line domain references, lower-axis anchors, no orphan axes, date-only
coordinates, invalid/numeric-date rejection, source-frame immutability,
crosshair configuration, and preservation of zoom settings and overlays.

See `tests.txt` for the full-suite result. Scanner logic, Entry Timing,
indicators, LINE and database operations are unchanged by this repair.
