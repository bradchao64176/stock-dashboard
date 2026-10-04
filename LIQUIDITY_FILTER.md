# Shared Trading Value / Liquidity Filter

The filter is applied **after existing technical selection and before Entry
Timing, result display and manual LINE preparation**. Scanner candidate
snapshots are not overwritten. No Yahoo request or SQLite write is performed
by the filter; changing controls on a live result page only filters that snapshot.

## Source and units

The current Yahoo daily pipeline (`services/yahoo_history.py`) downloads daily
OHLCV with auto_adjust=False and passes Volume through unchanged. Historical
storage preserves it. The Bull Flag chart explicitly labels Volume as shares
(股數/股); its indicator transformation adjusts price columns, not Volume.
The current adapter therefore explicitly passes `volume_unit='shares'`.

Read-only inspection found cached 2330.TW on 2026-10-02 with Close=2500 and
Volume=15,071,494 shares, and no official monetary-turnover field. The estimate
is NT$37,678,735,000. Volume is not multiplied by 1000 for these Yahoo rows.
The pure function also supports explicitly tagged `lots` inputs using ×1000;
no magnitude-based unit guessing occurs.

Priority within the bar for the relevant date:

1. A valid nonnegative official TWD amount: `Trading Value`, `Trade Value`,
   `Turnover Amount`, `TradingValue`, `TradeValue`, `成交金額`, or `成交值`.
2. Otherwise raw `Close * Volume`, with the explicitly configured volume-unit
   conversion. This is an **estimate**, not the sum of actual transaction amounts.
3. Missing/nonfinite/nonpositive Close or invalid Volume gives UNKNOWN. Valid
   zero volume gives zero estimated amount. Missing is never silently zero.

Generic turnover ratios and share-volume columns are not interpreted as TWD.
Official fields supplied by future adapters must already be monetary TWD.

## Settings and UI

`services/liquidity_filter.py` defines `DEFAULT_MIN_TRADING_VALUE=100_000_000`
and immutable `LiquidityConfig(enabled=True, min_trading_value=..., volume_unit='shares')`.
Equality passes: `trading_value >= minimum`. UNKNOWN is excluded when enabled,
even at threshold zero. Disabling retains both low-value and unknown candidates.

All five pages use **💰 最低成交值篩選**, checkbox **啟用最低成交值過濾**,
numeric **最低成交值（NT$）**, and presets 5千萬 / 1億 / 2億 / 5億. The numeric
control accepts a custom nonnegative value with step NT$10 million. The control
shows the threshold as NT$1.00 億, etc. It is below the live technical filters
and above the result table; on Backtest it is above the backtest settings.

Each page's dedicated `liquidity_<scanner>_enabled` and
`liquidity_<scanner>_minimum` session settings survive navigation. No mutable
global threshold can unexpectedly change another page. Controls pass an explicit
configuration to the shared filter.

Statistics show technical candidate count, below-threshold exclusions, UNKNOWN
exclusions, remaining count, and whether filtering is disabled. Entry-eligible
count remains in the existing LINE section. Result tables/CSVs include trading
value, date, source/status and pass flag; the visible 成交值 column uses 億.

## Five integrations

- Impulse MACD, including Strong: after existing strategy/confirmation filters.
- 台股下降旗形: after existing pattern filters and before its result tabs.
- 下降旗形多方缺口突破: after existing gap candidate filters.
- 多方未回補缺口: after existing unfilled-gap candidate filters.
- 下降旗形策略回測: filters generated signal candidates **before** the existing
  execution engine; the engine and scanner formulas themselves are unchanged.

## Backtest causality

`filter_backtest_signals()` copies the signal table and reads the bar at each
signal's exact `signal_date`. It never uses the final history row, today's
trading value, or any future bar. A missing signal-date bar is UNKNOWN; no
fallback to the latest date. Tests compare histories with/without a huge future
volume spike to prove identical historical decisions. Source histories, indexes,
signal indexes and input snapshots are retained unchanged.

The liquidity threshold is captured when **執行回測** is pressed. Existing
results retain their applied threshold/counts; changing controls requires a new
explicit backtest run to change historical results. The historical signal table
shows its signal-day values. The separate current-candidate manual LINE section
uses the current live Bull Flag snapshot with this page's explicitly supplied
liquidity configuration, never backtest trades.

## Entry and LINE

Only filtered rows reach the shared Entry adapter. Trading-value metadata is
carried into its output without changing Entry formulas. The existing manual
LINE formatter adds `成交值：NT$1.87 億`; sending eligibility, chunking, preview,
button callbacks, credentials and automatic/manual separation are unchanged.
Disabled filtering can retain UNKNOWN, which is explicitly displayed as UNKNOWN.
No automatic notification is introduced and no real LINE was sent during tests.

## Verification

See `validation/liquidity/REPORT.md`. New tests cover boundaries, presets/custom
values, disabled/UNKNOWN behavior, shares/lots, official precedence, historical
date/no-look-ahead, LINE input filtering, settings persistence and all five pages.
Existing UI tests explicitly disable this optional post-filter so their original
small-volume fixtures continue to test unchanged technical scanner behavior.
