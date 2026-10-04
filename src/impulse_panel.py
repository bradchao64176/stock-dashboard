"""Independent Impulse MACD scanner page using the shared SQLite history service."""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
from src.chart_interaction import apply_crosshair, apply_price_hover, normalize_chart_history, validate_date_chart
from plotly.subplots import make_subplots
import streamlit as st

from services.backtest_history import load_incremental_histories
from src.bull_flag_panel import ROOT, cached_universe
from src.impulse_macd import ImpulseConfig, scan_impulse_universe
from services.monthly_revenue import load_monthly_revenue
from src.strong_impulse import StrongConfig, scan_strong_universe, rank_strong
from backtesting.impulse import compare_impulse_variants
from backtesting.config import BacktestConfig, TradingCosts


def impulse_chart(data, event):
    data = normalize_chart_history(data)
    view = data.tail(160)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[.5, .2, .3], vertical_spacing=.04)
    fig.add_trace(go.Candlestick(x=view.index, open=view.Open, high=view.High, low=view.Low, close=view.Close, name="Price"), row=1, col=1)
    for column in ("MA20", "MA60"):
        fig.add_trace(go.Scatter(x=view.index, y=view[column], name=column), row=1, col=1)
    colors = ["gold" if day == event.golden_cross_date else "steelblue" for day in view.index]
    fig.add_trace(go.Bar(x=view.index, y=view.Volume, name="Volume", marker_color=colors), row=2, col=1)
    fig.add_trace(go.Scatter(x=view.index, y=view.Volume_MA20, name="Volume MA20"), row=2, col=1)
    fig.add_trace(go.Bar(x=view.index, y=view.Impulse_Histogram, name="Histogram"), row=3, col=1)
    for column in ("Impulse_MACD", "Impulse_Signal"):
        fig.add_trace(go.Scatter(x=view.index, y=view[column], name=column), row=3, col=1)
    fig.add_hline(y=0, row=3, col=1)
    fig.add_trace(go.Scatter(x=[event.golden_cross_date], y=[event.signal_close], mode="markers", name="Golden cross", marker=dict(size=12, color="gold")), row=1, col=1)
    fig.update_layout(height=650, xaxis_rangeslider_visible=False)
    apply_crosshair(fig, stacked=True)
    return validate_date_chart(apply_price_hover(fig, view))


def render_impulse_panel():
    st.title("Impulse MACD 黃金交叉選股")
    st.caption("Independent strategy · actual MACD/signal crossover · completed trading sessions")
    preset = st.selectbox("Strategy Preset", ["Pure Impulse Golden Cross", "Bullish Trend Golden Cross", "Strong Golden Cross"])
    advanced = preset != "Pure Impulse Golden Cross"
    with st.form("impulse_controls"):
        a, b, c = st.columns(3)
        market = a.selectbox("Market", ["All", "TWSE", "TPEx"])
        length = b.number_input("Impulse MA Length", 2, 200, 34)
        signal = c.number_input("Signal Length", 1, 100, 9)
        lookback = a.selectbox("Cross Lookback Days", [0, 1, 3, 5, 10, 20], index=3)
        positive = b.checkbox("Positive impulse on crossover day", advanced, disabled=advanced)
        close_ma = c.checkbox("Cross-day Close > MA20" if not advanced else "Current Close > MA20", advanced, disabled=advanced)
        ma_order = a.checkbox("Cross-day MA20 > MA60" if not advanced else "Current MA20 > MA60", advanced, disabled=advanced)
        rising = b.checkbox("Cross-day MA20 Rising" if not advanced else "Current MA20 Rising", advanced, disabled=advanced)
        slope = c.number_input("MA Slope Lookback", 1, 60, 5)
        if advanced:
            volume_ratio = a.number_input("Minimum Volume Ratio", .1, 20., 1.5, .1)
            volume_mode = b.selectbox("Volume Evaluation", ["CROSS_DAY", "CURRENT", "CROSS_DAY_OR_CURRENT", "CROSS_DAY_AND_CURRENT"])
            revenue_yoy = c.number_input("Minimum Revenue YoY (%)", -100., 1000., 10., 1.)
            positive_return = a.checkbox("Require positive cross-day return", False)
            max_revenue_age = b.number_input("Maximum revenue age (months)", 1, 12, 2)
        submitted = st.form_submit_button("Scan TWSE / TPEx")
    st.caption("Advanced presets: cross age ≤ N, current MA trend, crossover-day zone. Pure preset: latest N sessions and crossover-day MA filters.")
    if submitted:
        try:
            cfg = ImpulseConfig(int(length), int(signal), int(lookback), positive, close_ma, ma_order, rising, int(slope))
            with st.spinner("Reading shared SQLite history and downloading missing dates…"):
                universe, universe_errors = cached_universe()
                if universe_errors:
                    st.warning(str(universe_errors))
                if market != "All":
                    universe = universe[universe.market == market]
                end = date.today() + timedelta(days=1)
                start = date.today() - timedelta(days=max(365, int(length) * 5))
                histories, errors = load_incremental_histories(universe.ticker.tolist(), start, end, ROOT / "data" / "unfilled_gap_prices.db", refresh_lookback_months=1)
                revenues = pd.DataFrame()
                strong_cfg = StrongConfig()
                if advanced:
                    strong_cfg = StrongConfig(volume_ratio, volume_mode, revenue_yoy / 100, positive_return, int(max_revenue_age))
                    revenues, revenue_errors = load_monthly_revenue(ROOT / "data" / "unfilled_gap_prices.db")
                    if revenue_errors:
                        st.warning("Revenue refresh issues: " + str(revenue_errors))
                    snapshot = scan_strong_universe(universe, histories, revenues, cfg, strong_cfg, errors)
                else:
                    snapshot = scan_impulse_universe(universe, histories, cfg, errors)
                st.session_state.impulse_snapshot = snapshot
                st.session_state.impulse_config = cfg
                st.session_state.impulse_preset = preset
                st.session_state.impulse_strong_config = strong_cfg
                st.session_state.impulse_research = (universe, histories, revenues)
                st.session_state.pop("impulse_comparison", None)
        except Exception as error:
            st.error(str(error))
    snapshot = st.session_state.get("impulse_snapshot")
    if snapshot is None:
        st.info("Run a scan to calculate results. Existing scanners remain available in the sidebar.")
        return
    st.write("Completed scan parameters:", vars(st.session_state.impulse_config))
    st.write("Latest observed market session:", str(snapshot["market_date"]))
    st.write(snapshot["stats"])
    completed_preset = st.session_state.get("impulse_preset", "Pure Impulse Golden Cross")
    st.write("Completed preset:", completed_preset)
    result = snapshot["candidates"]
    if completed_preset != "Pure Impulse Golden Cross":
        only_strong = st.checkbox("Show Strong Candidates Only", value=completed_preset == "Strong Golden Cross")
        result = rank_strong(snapshot["events"], only_strong)
        if completed_preset == "Bullish Trend Golden Cross" and not only_strong and not result.empty:
            result = result[result.condition_above_zero & result.condition_close_above_ma20 & result.condition_ma20_above_ma60 & result.condition_ma20_rising]
        st.caption("Revenue month and availability are shown explicitly. UNKNOWN/STALE revenue fails strict selection. Score never overrides a failed condition.")
    # Explicit optional present-day confirmation; not part of historical signal generation.
    confirm = st.checkbox("Current histogram > 0 (optional confirmation)", False)
    if confirm and not result.empty:
        result = result[result.current_histogram > 0]
    from src.liquidity_panel import apply_liquidity_controls
    result = apply_liquidity_controls("impulse_macd", result, snapshot["details"])
    if result.empty:
        st.info("No qualifying golden crosses for these settings.")
    else:
        st.dataframe(result, use_container_width=True, hide_index=True)
        st.download_button("Download candidates CSV", result.to_csv(index=False).encode("utf-8-sig"), "impulse_macd_candidates.csv", "text/csv")
        ticker = st.selectbox("Inspect stock", result.ticker.tolist())
        event = result[result.ticker == ticker].iloc[0]
        if "strong_golden_cross" in event:
            st.subheader("🔥 強勢黃金交叉" if event.strong_golden_cross else "Not Strong")
            st.write({key: event[key] for key in event.index if key.startswith("condition_") or key.startswith("revenue_") or key in
                      ("failed_conditions", "cross_day_volume_ratio_20", "current_volume_ratio_20", "golden_cross_date", "trend_date", "strong_golden_cross_score", "volume_flag")})
            if event.revenue_status != "AVAILABLE":
                st.info("Revenue data unavailable or stale")
        st.plotly_chart(impulse_chart(snapshot["details"][ticker], event), use_container_width=True)
        with st.expander("All qualifying crossover events"):
            st.dataframe(snapshot["events"][snapshot["events"].ticker == ticker], hide_index=True)
    from src.entry_line_panel import render_scanner_entry_section
    render_scanner_entry_section("impulse_macd", result, snapshot, st.session_state.impulse_config)
    if not snapshot["issues"].empty:
        with st.expander("Skipped stocks / data issues"):
            st.dataframe(snapshot["issues"], hide_index=True)
    with st.expander("A–F historical strategy comparison"):
        st.caption("Uses all historical crossovers in the loaded history; next-open entry, existing cost/gap/overlap rules. Historical revenue requires an observed version available by signal-day 14:00. No historical revenue coverage means F is unavailable, not evidence of failure.")
        stop_method = st.selectbox("Research stop", ["ATR", "PERCENTAGE"])
        costs = st.checkbox("Research trading costs", True)
        if st.button("Run A–F comparison"):
            u, h, rev = st.session_state.impulse_research
            if rev.empty:
                rev, rev_errors = load_monthly_revenue(ROOT / "data" / "unfilled_gap_prices.db")
                if rev_errors:
                    st.warning(str(rev_errors))
            with st.spinner("Backtesting historical signals through the shared engine…"):
                st.session_state.impulse_comparison = compare_impulse_variants(u, h, rev, st.session_state.impulse_config,
                    st.session_state.impulse_strong_config, BacktestConfig(stop_method=stop_method, costs=TradingCosts(enabled=costs)))
        research = st.session_state.get("impulse_comparison")
        if research is not None:
            st.dataframe(research["comparison"], hide_index=True, use_container_width=True)
            for name in ("comparison", "trades", "forward_returns"):
                st.download_button("Export " + name, research[name].to_csv(index=False).encode("utf-8-sig"), "impulse_" + name + ".csv", "text/csv")
    st.caption("Raw Yahoo OHLC; corporate actions and vendor revisions can affect signals. Current listings introduce survivorship bias. No profitability claim or backtest result is implied.")
