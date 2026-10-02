# Entry Timing Engine — Strong Golden Cross Entry Analysis

## Usage and ownership

Run the existing Impulse MACD page with the Strong Golden Cross preset. The
additional **🎯 Entry Timing Analysis** section appears below the existing result
table and chart. It also appears under the Bullish preset, but analyzes only
the actual Strong candidates in the scanner snapshot, regardless of the display
toggle for non-Strong events. Its separate stock selector and CSV export do not
download data or rerun the scanner.

The engine consumes `snapshot['candidates']` and `snapshot['details']`. It does
not add/remove/rank candidates, change scores, read/write SQLite, download Yahoo
data, refresh revenue, send LINE messages, or execute orders. Prices mean the
last available scan candle; the UI explicitly displays that candle's date.

Existing modules reused:

- `src/strong_impulse.py`: existing selected candidates and scores, unchanged.
- `src/impulse_macd.py`: existing causal daily indicator engine and ATR14.
- `backtesting/signals.py:prepare_history`: existing configurable SMA True Range
  implementation for a non-default ATR period; raw price basis and valid-bar
  segmentation retained. This adapter requires at least 60 bars.
- Existing scanner snapshot: daily OHLCV already loaded by
  `services/backtest_history.py` from `daily_prices` (`date`, not `trade_date`).
- `backtesting/impulse.py` / existing execution engine are unchanged. Entry
  calculations are callable without Streamlit for future backtests; no new
  backtest strategy or trading execution is implemented here.

No existing standalone swing-low helper matched the requested prior-ten-day
minimum, so the new service computes that shifted rolling minimum.

## Formulas and precedence

Distance (%) = `(Close / MA20 - 1) * 100`.

Pullback zone = `[MA20, MA20 * 1.03]`. Requires price in zone, MA20 > MA60,
positive existing MA20 slope, MACD > Signal and Histogram > 0. Current volume
ratio < actual cross-day volume ratio is informational by default.

Breakout zone = `[previous 20-bar High maximum, maximum * 1.01]`. The current
bar is excluded. Requires price in zone, volume ratio >= 1.5, bullish MA structure,
MACD > Signal and Histogram > 0. Expanding histogram is required by default and
can be disabled in EntryTimingConfig.

Cross zone = `[actual cross-day High, High * 1.01]`. The date must exist in the
history and be a true golden cross according to the existing indicator output.
Requires price in zone, bullish MA structure/momentum and age <= 3 observed
trading sessions. Cross age is zero on the cross day, not calendar-day age.

Histogram direction: positive and increasing = EXPANDING; positive and flat or
decreasing = COOLING; zero/negative = WEAK. Missing inputs produce UNKNOWN entry
analysis, not a fabricated zero.

Decision order:

1. Missing/invalid required data or unavailable actual cross: UNKNOWN.
2. Close < MA20, MA20 <= MA60 or nonpositive MA20 slope: TREND_INVALIDATED.
3. Valid PULLBACK_ZONE, then BREAKOUT_ZONE, then CROSS_ENTRY.
4. Otherwise <= 7% distance: WATCH; >7% through 12%: EXTENDED; >12%:
   HIGHLY_EXTENDED. Machine-precision equality is respected at boundaries.

Independent boolean pattern flags preserve overlaps. A missed cross is stored
as `cross_entry_missed`; the main status continues to describe the current price
position. `MISSED` is an available display label, not an override of a valid
pullback/breakout or extension classification. This avoids hiding a new pullback
behind an old missed cross. Cross prices above the upper zone cannot be CROSS_ENTRY.

Primary reference zone uses the active pattern, prioritizing pullback over
breakout over cross. Without an active pattern, it remains the pullback zone;
even an extended/invalidated stock never substitutes current Close as its entry.
All zones are references, not instructions to trade.

Reference Entry = midpoint of primary zone. ATR14 reuses the existing simple
14-bar average of True Range (max of High-Low, |High-previous Close|,
|Low-previous Close|). Recent swing low excludes the current bar.

STRUCTURAL stop: prefer a positive previous-ten-bar minimum Low strictly below
Reference Entry; otherwise use `MA20 - 0.5 * ATR`. MA20_ATR mode uses only that
ATR-buffered candidate. Reject nonpositive/nonfinite stops and stops >= entry.

Risk/share = Reference Entry - Reference Stop; Risk % = Risk/share / Reference
Entry * 100; 2R = Entry + 2 * Risk/share; 3R = Entry + 3 * Risk/share. Invalid
risk sets INVALID_RISK_STRUCTURE and leaves targets null. Targets are risk-unit
references, not price forecasts; fees/slippage are not included.

## Configuration

All values are centralized in `services/entry_timing_config.py`; percentage
thresholds below are fractions, while result distance/risk fields use percent.

| Parameter | Default |
|---|---|
| pullback_low_pct / pullback_high_pct | 0 / 0.03 |
| watch_max_distance_pct / extended_max_distance_pct | 0.07 / 0.12 |
| breakout_buffer_pct / cross_entry_buffer_pct | 0.01 / 0.01 |
| breakout_volume_ratio | 1.5 |
| max_cross_entry_age_days | 3 trading sessions |
| resistance_lookback | 20 |
| atr_period / atr_stop_multiplier | 14 / 0.5 |
| swing_lookback | 10 |
| stop_mode | STRUCTURAL (alternative MA20_ATR) |
| require_volume_contraction | False |
| require_expanding_breakout | True |

## Historical use

`calculate_entry_analysis(candidate, history, config, asof, impulse_config)`
truncates history to the supplied analysis date before calculating references.
Pass raw OHLCV plus the scanner's ImpulseConfig, or its already-calculated causal
details. No future bar enters resistance, swing, ATR or cross age. Cross dates
after asof are rejected. The caller must supply candidates that were actually
selected at that historical time, including then-available revenue; this layer
cannot remove survivorship bias from a future-selected candidate list.

## Verification and files

Baseline before changes: 130 existing tests passed. See
`validation/entry_timing` for database before/after evidence and final results.
The current checkout at implementation time lacks Intraday Monitor and LINE
service source/tests. Their database was left untouched; runtime regression
claims for those absent modules are not possible.

New: entry_timing_config.py, entry_timing_service.py, entry_timing_panel.py,
test_entry_timing.py, this document, and validation evidence.
Only existing application file modified: `src/impulse_panel.py` (three-line
additive section call). All selection formulas, data services and backtesting
files are unchanged. No database migration or persistent Entry table is needed.
