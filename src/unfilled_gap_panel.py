"""Independent general-gap strategy with causal gap-day/current MA controls."""
from dataclasses import asdict
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services.backtest_history import load_backtest_histories
from src.bull_flag_panel import ROOT, cached_universe
from src.bull_flag_gap_panel import LABELS
from src.unfilled_gap import scan_unfilled_universe, filter_unfilled_events
from src.unfilled_gap_config import UnfilledGapConfig, TrendConfig


def unfilled_chart(data, event):
    view = data.tail(140)
    chart = go.Figure(go.Candlestick(x=view.index, open=view.Open, high=view.High, low=view.Low, close=view.Close, name="OHLC"))
    for period in (5, 10, 20, 60):
        chart.add_trace(go.Scatter(x=view.index, y=view[f"MA{period}"], name=f"MA{period}"))
    chart.add_shape(type="rect", x0=event.gap_date, x1=event.price_date, y0=event.gap_bottom, y1=event.gap_top,
                    fillcolor="orange", opacity=.22, line=dict(color="orange"), layer="below")
    chart.add_trace(go.Scatter(x=[event.gap_date], y=[event.gap_day_close], mode="markers", name="Gap day", marker=dict(size=12)))
    chart.update_layout(height=500, xaxis_rangeslider_visible=False, yaxis_title="TWD")
    return chart


def render_unfilled_panel():
    st.title("多方未回補缺口選股")
    st.caption("Unfilled Bullish Gap Scanner · 獨立策略，不要求下降旗形 · 缺口日與目前趨勢分開計算")
    with st.expander("掃描設定 / 趨勢條件 Trend Filters", expanded="unfilled_snapshot" not in st.session_state):
        with st.form("unfilled_controls"):
            a, b, c = st.columns(3)
            market = a.selectbox("Market", ["All", "TWSE", "TPEx"])
            limit = b.number_input("最多股票數（0 = 全市場）", 0, 3000, 0)
            lookback = c.selectbox("Gap Lookback Days", [5, 10, 20, 30, 60], index=2)
            return_days = a.number_input("Return Lookback Days", 1, 120, 20)
            min_return = b.number_input("Minimum Recent Return (%)", -90.0, 500.0, 10.0, 1.0)
            gap_pct = c.selectbox("Minimum Gap (%)", [0.0, .5, 1.0, 1.5, 2.0, 3.0, 5.0], index=2)
            definition = a.selectbox("Gap Definition", ["FULL_GAP", "OPEN_GAP"])
            untouched = b.checkbox("Only Untouched Gaps", value=False)
            refresh = c.checkbox("重新下載價格資料", value=False)
            st.write("趨勢條件 / Trend Filters")
            close_above = a.checkbox("Close > MA20", value=True)
            ma20_above = b.checkbox("MA20 > MA60", value=True)
            rising20 = c.checkbox("MA20 Rising", value=True)
            rising60 = a.checkbox("MA60 Rising", value=False)
            alignment = b.checkbox("Close > MA5 > MA10 > MA20 > MA60", value=False)
            slope_days = c.number_input("MA Slope Lookback", 1, 60, 5)
            trend_mode = a.selectbox("Trend Evaluation", ["GAP_DAY", "CURRENT", "GAP_DAY_AND_CURRENT"], index=2,
                                     format_func=lambda x: {"GAP_DAY": "Gap Day", "CURRENT": "Current", "GAP_DAY_AND_CURRENT": "Gap Day + Current"}[x])
            distance_on = b.checkbox("限制 MA20 / MA60 距離", value=False)
            min_distance = c.number_input("Minimum MA20–MA60 Distance (%)", -90.0, 500.0, 0.0)
            cap_distance = a.checkbox("Maximum Distance Enabled", value=False)
            max_distance = b.number_input("Maximum MA20–MA60 Distance (%)", -90.0, 500.0, 30.0)
            volume_on = c.checkbox("Gap Volume Confirmation", value=False)
            volume_ratio = a.number_input("Minimum Gap Volume Ratio", 0.0, 10.0, 1.2, .1)
            submitted = st.form_submit_button("執行未回補缺口選股")
        st.caption("報酬門檻以目前收盤計算；Trend Evaluation 控制 MA 條件套用的日期。"
                   "所有斜率使用指定交易日間的 MA 比值變化，非一天差分。")
        if submitted:
            try:
                trend = TrendConfig(close_above, ma20_above, rising20, rising60, alignment, int(slope_days), trend_mode,
                                    distance_on, min_distance / 100, max_distance / 100 if cap_distance else None)
                cfg = UnfilledGapConfig(trend=trend, gap_lookback_days=lookback, return_lookback_days=int(return_days),
                                        min_return_pct=min_return / 100, gap_definition=definition, min_gap_pct=gap_pct / 100,
                                        only_untouched_gaps=untouched, require_volume_confirmation=volume_on,
                                        min_volume_ratio=volume_ratio)
                universe, errors = cached_universe()
                if market != "All":
                    universe = universe[universe.market == market]
                universe = universe.sort_values("stock_code")
                if limit:
                    universe = universe.head(int(limit))
                if universe.empty:
                    raise ValueError(f"沒有官方股票名單：{errors}")
                end = date.today() + timedelta(days=1)
                start = (pd.Timestamp(date.today()) - pd.DateOffset(years=1)).date()
                bar = st.progress(0.0, text="讀取快取／Yahoo 日線…")
                histories, failures = load_backtest_histories(tuple(universe.ticker), start, end,
                    ROOT / "data" / "unfilled_gap_prices.db", refresh=refresh, actions=True,
                    progress=lambda done, total: bar.progress(done / total, text=f"下載 {done}/{total}"))
                snapshot = scan_unfilled_universe(universe, histories, cfg,
                    progress=lambda done, total: bar.progress(done / total, text=f"分析 {done}/{total}"))
                bar.empty()
                snapshot.update(universe_errors=errors, download_errors=failures)
                st.session_state["unfilled_snapshot"] = snapshot
            except Exception as error:
                st.error(f"未完成，保留先前結果：{error}")
    snapshot = st.session_state.get("unfilled_snapshot")
    if snapshot is None:
        st.info("預設全市場；按執行後下載一次。調整參數重跑時可重用本機價格快取。")
        return
    cfg = snapshot["config"]
    st.caption(f'市場資料日：{snapshot["market_date"]} · 掃描 UTC：{snapshot["scan_time"]} · '
               f'{cfg.gap_definition} · {cfg.gap_lookback_days} 交易日 · {cfg.trend.trend_evaluation}')
    for market, error in snapshot["universe_errors"].items():
        st.warning(f"{market} 名單不完整：{error}")
    for col, label, key in zip(st.columns(4), ["股票總數", "分析成功", "略過", "候選股票"],
                              ["total", "analyzed", "skipped", "candidates"]):
        col.metric(label, snapshot["stats"][key])
    with st.expander("本次參數／資料品質"):
        st.json(asdict(cfg))
        st.write(snapshot["download_errors"])
        st.dataframe(pd.DataFrame(snapshot["issues"]), hide_index=True)
    statuses = st.multiselect("Gap Status", list(LABELS), ["UNTOUCHED", "PARTIALLY_FILLED"], format_func=lambda x: LABELS[x])
    candidates = filter_unfilled_events(snapshot["events"], cfg, statuses=statuses)
    st.download_button("候選 CSV", candidates.to_csv(index=False).encode("utf-8-sig"), "unfilled_candidates.csv", "text/csv")
    st.download_button("全部事件 CSV（含歷史 MA）", snapshot["events"].to_csv(index=False).encode("utf-8-sig"), "unfilled_events.csv", "text/csv")
    if candidates.empty:
        st.info("沒有符合條件的股票；請查看資料日期、條件與略過紀錄。")
        return
    columns = ["rank", "stock_code", "stock_name", "market", "current_close", "recent_return_pct", "gap_date", "gap_pct",
               "gap_fill_pct", "current_ma20", "current_ma60", "current_ma20_slope_pct", "current_ma60_slope_pct",
               "ma20_ma60_distance_pct", "gap_day_ma20", "gap_day_ma60", "gap_status", "unfilled_gap_score"]
    table = candidates[columns].copy()
    for column in table:
        if column.endswith("_pct"):
            table[column] *= 100
    st.dataframe(table, hide_index=True, use_container_width=True)
    st.caption("表格 *_pct 欄位為百分比數值；CSV 保留小數比例（0.10 = 10%）。")
    ticker = st.selectbox("查看個股", candidates.ticker.tolist(), key=f'unfilled_{snapshot["scan_time"]}')
    row = candidates[candidates.ticker == ticker].iloc[0]
    st.subheader(f'{row.stock_code} {row.stock_name} · {LABELS[row.gap_status]}')
    st.dataframe(pd.DataFrame([row]), hide_index=True)
    st.dataframe(pd.DataFrame([dict(component=k[6:], points=v) for k, v in row.items()
                               if k.startswith("score_") and k != "score_at_signal"]), hide_index=True)
    st.plotly_chart(unfilled_chart(snapshot["details"][ticker], row), use_container_width=True)
    with st.expander("此股所有缺口事件"):
        st.dataframe(snapshot["events"][snapshot["events"].ticker == ticker], hide_index=True)
    st.caption("MA 金叉日期僅在歷史資料中觀察到明確穿越時顯示；資料起點已多頭時不猜測交叉日。"
               "目前未回補狀態不能用來篩選過去進場交易；有存活者偏差及日線資料限制。")
