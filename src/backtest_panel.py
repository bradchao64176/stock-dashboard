"""Explicit-run backtest UI. Presentation controls operate only on saved results."""
from dataclasses import asdict
from datetime import date, timedelta
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backtesting.config import BacktestConfig, TradingCosts
from backtesting.engine import build_signal_set, execute_backtest
from backtesting.metrics import equity_curve, parameter_analysis
from services.backtest_history import load_backtest_histories
from src.bull_flag_config import BullFlagConfig
from src.bull_flag_panel import ROOT, cached_universe


@st.cache_data(ttl=3600, max_entries=2, show_spinner=False)
def cached_signal_set(universe, histories, config, start, end):
    bar = st.progress(0.0, text="產生歷史訊號…")
    result = build_signal_set(universe, histories, config, start, end,
                              progress=lambda done, total: bar.progress(done / total, text=f"分析 {done} / {total}"))
    bar.empty()
    return result


def trade_chart(data, row):
    start = max(0, int(data.index.get_loc(row.flagpole_start)) - 10)
    end = min(len(data), int(row.exit_index) + 6)
    visible = data.iloc[start:end]
    fig = go.Figure(go.Candlestick(x=visible.index, open=visible.Open, high=visible.High,
                                 low=visible.Low, close=visible.Close, name="OHLC"))
    for name in ("MA20", "MA60"):
        fig.add_trace(go.Scatter(x=visible.index, y=visible[name], name=name))
    dates = data.loc[row.flag_start:row.signal_date].index
    for prefix, label in (("high", "Flag resistance"), ("low", "Flag support")):
        fig.add_trace(go.Scatter(x=dates, y=[row[f"{prefix}_intercept"] + i * row[f"{prefix}_slope"]
                                             for i in range(len(dates))], name=label, line=dict(dash="dash")))
    for value, label, color in ((row.entry_price, "Entry", "blue"), (row.stop_price, "Stop", "red"),
                                (row.target_price, "Target", "green")):
        fig.add_shape(type="line", x0=row.entry_date, x1=row.exit_date, y0=value, y1=value,
                      line=dict(color=color, dash="dot"))
        fig.add_annotation(x=row.entry_date, y=value, text=label, showarrow=False)
    for when, price, label in ((row.signal_date, row.signal_close, "Signal"),
                                (row.entry_date, row.entry_price, "Entry"), (row.exit_date, row.exit_price, "Exit")):
        if pd.notna(price):
            fig.add_trace(go.Scatter(x=[when], y=[price], mode="markers", name=label, marker=dict(size=12)))
    fig.add_vrect(x0=row.flagpole_start, x1=row.flag_start, fillcolor="green", opacity=.08, line_width=0)
    fig.update_layout(height=520, xaxis_rangeslider_visible=False, yaxis_title="Yahoo OHLC (TWD)")
    return fig


def fmt(value, percent=False):
    if pd.isna(value):
        return "N/A"
    return f"{value:.2%}" if percent else f"{value:,.3f}"


def render_backtest_panel():
    st.title("下降旗形策略回測")
    st.caption("Bull Flag Backtest · 下一交易日開盤進場 · 以實際資料比較 +nR / −1R")
    st.warning("目前使用現存 TWSE／TPEx 公司名單，有存活者偏差。歷史結果不代表未來獲利。")
    with st.expander("回測設定", expanded="bull_flag_backtest" not in st.session_state):
        with st.form("backtest_controls"):
            a, b, c = st.columns(3)
            market = a.selectbox("Market", ["All", "TWSE", "TPEx"])
            years = b.selectbox("Historical Period", [3, 5, 10], index=1, format_func=lambda n: f"{n}Y")
            end = c.date_input("資料截止日", date.today())
            max_stocks = a.number_input("最多股票數（0 = 全市場）", 0, 3000, 20)
            codes = b.text_input("指定股票代碼（選填，逗號分隔）", help="空白時依官方代碼排序取前 N 檔；樣本不代表全市場。")
            force = c.checkbox("重新下載價格資料", value=False)
            min_score = a.slider("Minimum Bull Flag Score", 0, 100, 60)
            min_pole = b.slider("Minimum Flagpole Return (%)", 5, 80, 15)
            pole_days = c.number_input("Flagpole Days", 10, 20, 20)
            flag_lengths = a.slider("Flag Length", 5, 15, (5, 15))
            pullback = b.slider("Maximum Pullback / pole advance (%)", 10, 80, 50)
            contraction = c.checkbox("要求旗形量縮", value=False)
            require_volume = a.checkbox("Breakout Volume Confirmation", value=True)
            volume_multiplier = b.number_input("Breakout Volume Multiplier", 0.1, 5.0, 1.2, .1)
            method = c.selectbox("Stop Loss Method", ["FLAG_LOW", "ATR", "PERCENTAGE"],
                                  format_func=lambda x: {"FLAG_LOW": "Flag Swing Low", "ATR": "ATR", "PERCENTAGE": "Percentage"}[x])
            atr_period = a.number_input("ATR Period", 2, 60, 14)
            atr_multiplier = b.number_input("ATR Multiplier", .1, 10.0, 1.5, .1)
            stop_pct = c.number_input("Percentage Stop (%)", .1, 50.0, 5.0, .1)
            rr_targets = a.multiselect("Risk / Reward Targets", [1.0, 1.5, 2.0, 2.5, 3.0], [1.0, 1.5, 2.0, 2.5, 3.0])
            horizons = b.multiselect("Maximum Holding Days", [5, 10, 20, 30], [5, 10, 20, 30])
            policy = c.selectbox("Same-Bar Policy", ["CONSERVATIVE", "OPTIMISTIC", "EXCLUDE"])
            costs_on = a.checkbox("Trading Costs", value=True)
            brokerage = b.number_input("Brokerage Fee per side (%)", 0.0, 2.0, .1425, .01, format="%.4f")
            min_fee = c.number_input("Minimum Brokerage per side (TWD)", 0.0, 1000.0, 20.0)
            tax = a.number_input("Securities Transaction Tax (%)", 0.0, 2.0, .3, .01)
            slip = b.number_input("Slippage per side (%)", 0.0, 5.0, .05, .01)
            overlap = c.checkbox("允許同股重疊交易", value=False)
            capital = a.number_input("Starting Capital (TWD)", 1000.0, 1000000000.0, 1000000.0)
            sizing = b.selectbox("Position Sizing", ["FIXED_RISK", "FIXED_SHARES"])
            risk_pct = c.number_input("Risk Per Trade (% of initial capital)", .01, 20.0, 1.0)
            shares = a.number_input("Position Size (shares, FIXED_SHARES)", 1, 10000000, 1000)
            split_on = b.checkbox("Training / Out-of-sample split", value=False)
            split = c.date_input("Out-of-sample begins", date(end.year - 1, 1, 1))
            submitted = st.form_submit_button("執行回測")
        st.caption("預設費率為可修改的研究假設；賣出稅一律使用輸入值，不自動套用當沖優惠。"
                   "ATR 採簡單移動平均 True Range。每個 RR／持有期獨立模擬。")
        if submitted:
            if not rr_targets or not horizons:
                st.error("請至少選一組 RR 與持有期。")
            else:
                try:
                    start = (pd.Timestamp(end) - pd.DateOffset(years=years)).date()
                    if split_on and not start < split <= end:
                        raise ValueError("分割日必須在回測期間內")
                    config = BacktestConfig(
                        detector=BullFlagConfig(min_bull_flag_score=min_score, min_flagpole_return=min_pole / 100,
                                                flagpole_days=int(pole_days), min_flag_days=flag_lengths[0],
                                                max_flag_days=flag_lengths[1], max_retracement=pullback / 100,
                                                breakout_volume_multiplier=volume_multiplier),
                        require_breakout_volume=require_volume, require_volume_contraction=contraction,
                        stop_method=method, atr_period=int(atr_period), atr_multiplier=atr_multiplier,
                        stop_pct=stop_pct / 100, rr_targets=tuple(rr_targets), holding_periods=tuple(horizons),
                        same_bar_policy=policy, allow_overlap=overlap, starting_capital=capital,
                        sizing_mode=sizing, risk_per_trade=risk_pct / 100, position_shares=int(shares),
                        costs=TradingCosts(costs_on, brokerage / 100, min_fee, tax / 100, slip / 100))
                    with st.spinner("取得名單與行情…"):
                        universe, roster_errors = cached_universe()
                        if market != "All":
                            universe = universe[universe.market == market]
                        if codes.strip():
                            requested = {code.strip() for code in codes.replace("，", ",").split(",") if code.strip()}
                            unknown = requested - set(universe.stock_code)
                            if unknown:
                                st.warning(f"不在所選官方市場名單：{', '.join(sorted(unknown))}")
                            universe = universe[universe.stock_code.isin(requested)]
                        universe = universe.sort_values("stock_code")
                        if max_stocks:
                            universe = universe.head(int(max_stocks))
                        if universe.empty:
                            raise ValueError(f"無符合條件股票；官方來源錯誤：{roster_errors}")
                        bar = st.progress(0.0, text="讀取本機快取／下載日線…")
                        histories, errors = load_backtest_histories(
                            tuple(universe.ticker), start - timedelta(days=240), end + timedelta(days=1),
                            ROOT / "data" / "backtest_prices.db", refresh=force,
                            progress=lambda done, total: bar.progress(done / total, text=f"下載 {done}/{total}"))
                        bar.empty()
                    signal_set = cached_signal_set(universe, histories, config, str(start), str(end))
                    with st.spinner("模擬各組 RR／持有期…"):
                        result = execute_backtest(signal_set, config, str(split) if split_on else None, str(end))
                    result.update(histories=signal_set["histories"], download_errors=errors,
                                  roster_errors=roster_errors, start=str(start), end=str(end))
                    st.session_state["bull_flag_backtest"] = result
                except Exception as error:
                    st.error(f"回測未完成，保留先前結果：{error}")
    result = st.session_state.get("bull_flag_backtest")
    if result is None:
        st.info("設定參數後按「執行回測」。預設先取 20 檔；全市場可將最多股票數設為 0。")
        return
    render_results(result)


def render_results(result):
    config = result["config"]
    comparison = result["comparison"]
    st.caption(f'訊號期間：{result["start"]} — {result["end"]} · 快照：{result["generated_at"]}')
    for market, error in result["roster_errors"].items():
        st.warning(f"官方名單缺少 {market}：{error}")
    a, b, c = st.columns(3)
    sample = a.selectbox("顯示資料區段", comparison["sample"].unique().tolist())
    horizon_options = list(config.holding_periods)
    horizon = b.selectbox("顯示持有期", horizon_options, index=horizon_options.index(20) if 20 in horizon_options else 0)
    rr_options = list(config.rr_targets)
    rr = c.selectbox("顯示 RR", rr_options, index=rr_options.index(2.0) if 2.0 in rr_options else 0)
    table = comparison[(comparison["sample"] == sample) & (comparison.max_holding_days == horizon)]
    selected_summary = table[table.RR_target == rr].iloc[0]
    cols = st.columns(4)
    for col, label, value in zip(cols, ["Stocks analyzed", "Signals", "Trades", f"1:{rr:g} Win Rate"],
                                  [result["stats"]["stocks_analyzed"], selected_summary.total_signals,
                                   selected_summary.total_trades, fmt(selected_summary.win_rate, True)]):
        col.metric(label, value)
    cols = st.columns(4)
    for col, label, value in zip(cols, ["Break-even (before costs)", "Expectancy (net R)", "Profit Factor (net R)", "Realized Max DD"],
                                  [fmt(selected_summary.break_even_win_rate, True), fmt(selected_summary.expectancy),
                                   fmt(selected_summary.profit_factor), fmt(selected_summary.maximum_drawdown, True)]):
        col.metric(label, value)
    st.caption(f'平均持有 {fmt(selected_summary.average_holding_days)} 日 · '
               f'模糊 K 棒 {int(selected_summary.ambiguous_trades)} · 期末／缺資料未完成 {int(selected_summary.censored)}')
    st.info("勝率 = WIN / (WIN + LOSS + TIMEOUT)。EXCLUDE 模糊交易及 CENSORED 不列入分母；"
            "Expectancy 使用實際淨 R，包含 TIMEOUT 損益。損益曲線是獨立交易研究，非受資金限制的投資組合。")
    sort = st.selectbox("比較排序", ["expectancy", "profit_factor", "win_rate", "maximum_drawdown"])
    st.dataframe(table.sort_values(sort, ascending=sort == "maximum_drawdown"), hide_index=True, use_container_width=True)
    with st.expander("持有期比較（目前 RR）"):
        st.dataframe(comparison[(comparison["sample"] == sample) & (comparison.RR_target == rr)],
                     hide_index=True, use_container_width=True)
    st.caption("比率欄位使用小數（0.25 = 25%）。低回撤或高勝率不等同較佳未來策略。")
    trades = result["trades"]
    summary_export = pd.DataFrame([dict(result["stats"], start=result["start"], end=result["end"],
                                        generated_at=result["generated_at"], settings=json.dumps(asdict(config)))])
    for col, label, frame, filename in zip(st.columns(3), ["Backtest Summary CSV", "Trade History CSV", "RR Comparison CSV"],
                                         [summary_export, trades, comparison], ["summary.csv", "trades.csv", "rr_comparison.csv"]):
        col.download_button(label, frame.to_csv(index=False).encode("utf-8-sig"), filename, "text/csv")
    with st.expander("資料／跳過紀錄與使用參數"):
        st.json(asdict(config))
        st.write(result["download_errors"])
        st.dataframe(pd.DataFrame(result["issues"]), hide_index=True)
        st.dataframe(result["skipped"], hide_index=True)
    if trades.empty:
        st.info("沒有可進場交易；未填入示範結果。")
        return
    selected = trades[(trades["sample"] == sample) & (trades.RR_target == rr) & (trades.max_holding_days == horizon)]
    if selected.empty:
        st.info("此情境沒有交易。")
        return
    curve = equity_curve(selected, config.starting_capital)
    if not curve.empty:
        st.plotly_chart(go.Figure(go.Scatter(x=curve.date, y=curve.cumulative_R, name="Cumulative net R"))
                        .update_layout(title="Chronological cumulative R (realized exits)"), use_container_width=True)
        st.plotly_chart(go.Figure(go.Scatter(x=curve.date, y=curve.drawdown_pct * 100, fill="tozeroy"))
                        .update_layout(title="Realized research drawdown", yaxis_title="Drawdown %"), use_container_width=True)
    st.caption("部位按初始資金固定風險額或固定股數計算；無跨股資金上限、未實現損益或複利。"
               "MFE／MAE 包含出場日整根 K 棒極值，為日線範圍界限，可能包含出場後波動。跳空開盤出場僅用開盤價。")
    for col, field in zip(st.columns(2), ["MFE_R", "MAE_R"]):
        col.plotly_chart(go.Figure(go.Histogram(x=selected[field], name=field)).update_layout(title=field), use_container_width=True)
    st.plotly_chart(go.Figure(go.Scatter(x=selected.MAE_R, y=selected.MFE_R, mode="markers",
                                        text=selected.ticker)).update_layout(xaxis_title="MAE_R", yaxis_title="MFE_R"),
                    use_container_width=True)
    dimension = st.selectbox("參數分組", ["Bull Flag Score", "Market", "Flagpole strength", "Pullback depth",
                                          "Volume contraction", "Breakout volume"])
    st.dataframe(parameter_analysis(selected, dimension, rr, config.starting_capital), hide_index=True)
    st.subheader("個別交易檢視")
    index = st.selectbox("Trade", selected.index.tolist(),
                          key=f'trade_{result["generated_at"]}_{sample}_{horizon}_{rr}', format_func=lambda i:
                          f'{selected.loc[i, "ticker"]} · {selected.loc[i, "signal_date"].date()} · {selected.loc[i, "outcome"]}')
    row = selected.loc[index]
    st.dataframe(pd.DataFrame([row]), hide_index=True)
    st.plotly_chart(trade_chart(result["histories"][row.ticker], row), use_container_width=True)
