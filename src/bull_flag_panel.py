"""Bull flag page: explicit refresh, cached inputs, snapshot-only display filters."""
from pathlib import Path
from contextlib import closing
import sqlite3

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services.taiwan_universe import fetch_taiwan_universe
from services.yahoo_history import download_histories
from src.bull_flag import scan_universe, filter_candidates
from src.bull_flag_config import BullFlagConfig

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"FORMING": "🟡 形成中", "BREAKOUT": "🟢 突破"}


@st.cache_data(ttl=86400, show_spinner=False)
def cached_universe():
    return fetch_taiwan_universe()


@st.cache_data(ttl=3600, max_entries=4, show_spinner=False)
def cached_histories(tickers, include_actions=False):
    bar = st.progress(0.0, text="下載 Yahoo Finance 日線…")
    result = download_histories(tickers, actions=include_actions, progress=lambda done, total: bar.progress(
        done / total, text=f"下載日線 {done} / {total}"))
    bar.empty()
    return result


def load_news_scores(path, codes):
    """Reuse latest stored analyses and existing importance-weighted sentiment formula.

    No collection or inference on page reruns. Up to 20 articles per stock, same as
    the PChome panel. Missing analyses remain missing, not neutral scores.
    """
    if not path.exists() or not codes:
        return {}
    scores = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        for code in codes:
            rows = connection.execute("""
                SELECT x.sentiment_score, x.importance_score
                FROM articles a JOIN article_stocks s ON s.article_id = a.id
                LEFT JOIN article_analyses x ON x.id = (
                    SELECT x2.id FROM article_analyses x2
                    WHERE x2.article_id=a.id AND x2.stock_symbol=s.stock_symbol
                    ORDER BY x2.id DESC LIMIT 1)
                WHERE s.stock_symbol = ? ORDER BY a.published_at DESC LIMIT 20
            """, (code,)).fetchall()
            valid = [(sentiment, importance) for sentiment, importance in rows
                     if sentiment is not None and importance is not None and importance > 0]
            if valid:
                scores[code] = (sum(s * w for s, w in valid) / sum(w for _, w in valid) + 1) * 50
    return scores


def candidate_chart(data, result):
    visible = data.tail(100)
    fig = go.Figure(go.Candlestick(x=visible.index, open=visible.Open, high=visible.High,
                                 low=visible.Low, close=visible.Close, name="日線"))
    for name in ("MA20", "MA60"):
        fig.add_trace(go.Scatter(x=visible.index, y=visible[name], name=name))
    dates = data.loc[result.flag_start:].index
    for prefix, label in (("high", "下降阻力線"), ("low", "下降支撐線")):
        values = [result[f"{prefix}_intercept"] + result[f"{prefix}_slope"] * x for x in range(len(dates))]
        fig.add_trace(go.Scatter(x=dates, y=values, name=label, line=dict(dash="dash")))
    fig.add_vrect(x0=result.flagpole_start, x1=result.flag_start, fillcolor="green", opacity=0.08,
                 line_width=0)
    if result.status == "BREAKOUT":
        fig.add_trace(go.Scatter(x=[result.price_date], y=[result.close], mode="markers",
                                marker=dict(size=14, symbol="triangle-up"), name="突破"))
    fig.update_layout(height=500, xaxis_rangeslider_visible=False, yaxis_title="TWD",
                      margin=dict(l=10, r=10, t=20, b=10))
    return fig


def render_bull_flag_panel():
    st.title("台股下降旗形選股")
    st.caption("Taiwan Bull Flag Scanner · TWSE / TPEx 普通股 · Yahoo Finance 日線")
    config = BullFlagConfig()
    with st.expander("掃描設定與資料更新", expanded="bull_flag_snapshot" not in st.session_state):
        st.caption("首次取得約一年資料。官方名單快取 24 小時，行情快取 1 小時；篩選不會觸發下載。")
        with st.form("bull_flag_scan"):
            scan_market = st.selectbox("下載市場", ["All", "TWSE", "TPEx"])
            pole_days = st.number_input("旗桿交易日", 10, 20, config.flagpole_days)
            slope = st.number_input("斜率相對差容許值", 0.05, 2.0, config.slope_tolerance, 0.05)
            multiplier = st.number_input("突破成交量倍數", 1.0, 3.0, config.breakout_volume_multiplier, 0.1)
            force = st.checkbox("重新下載（清除此選股器的資料快取）")
            submitted = st.form_submit_button("更新資料並掃描")
        if submitted:
            if force:
                cached_universe.clear()
                cached_histories.clear()
            with st.spinner("取得官方股票清單與分析行情…"):
                universe, universe_errors = cached_universe()
                if scan_market != "All":
                    universe = universe[universe.market == scan_market]
                if universe.empty:
                    st.error(f"無可用官方股票清單：{universe_errors}。未取代先前快照。")
                else:
                    histories, errors = cached_histories(tuple(universe.ticker))
                    selected_config = BullFlagConfig(flagpole_days=int(pole_days), slope_tolerance=slope,
                                                     breakout_volume_multiplier=multiplier)
                    snapshot = scan_universe(universe, histories, selected_config, errors)
                    snapshot["universe_errors"] = universe_errors
                    snapshot["config"] = selected_config
                    snapshot["market"] = scan_market
                    try:
                        snapshot["news_scores"] = load_news_scores(
                            ROOT / "data" / "stock_news.db", snapshot["patterns"].stock_code.unique().tolist())
                    except sqlite3.Error as error:
                        snapshot["news_scores"] = {}
                        snapshot["news_error"] = str(error)
                    st.session_state["bull_flag_snapshot"] = snapshot
    snapshot = st.session_state.get("bull_flag_snapshot")
    if snapshot is None:
        st.info("按「更新資料並掃描」開始。全市場首次下載可能需要數分鐘。")
        return
    st.caption(f'掃描時間 (UTC)：{snapshot["scan_time"]} · 市場：{snapshot["market"]} · '
               f'旗桿：{snapshot["config"].flagpole_days} 日 · 突破量：{snapshot["config"].breakout_volume_multiplier:.2f} 倍')
    for market, error in snapshot["universe_errors"].items():
        st.warning(f"{market} 官方名單取得失敗；本次可能僅涵蓋部分市場：{error}")
    if snapshot.get("news_error"):
        st.warning(f'既有 News Score 暫不可讀取：{snapshot["news_error"]}')
    stats = snapshot["stats"]
    labels = dict(total="股票總數", downloaded="下載成功", analyzed="分析成功", candidates="型態候選",
                  forming="形成中", breakout="突破", skipped="略過", errors="錯誤")
    for offset in (0, 4):
        for col, key in zip(st.columns(4), list(labels)[offset:offset + 4]):
            col.metric(labels[key], stats[key])
    st.caption("候選統計為篩選前每檔最高分型態；略過為資料驗證失敗，錯誤為下載或分析失敗。")
    with st.expander("略過與錯誤紀錄"):
        st.dataframe(pd.DataFrame(snapshot["issues"], columns=["ticker", "stage", "reason"]), hide_index=True)
    st.subheader("篩選候選")
    a, b, c = st.columns(3)
    market = a.selectbox("Market", ["All", "TWSE", "TPEx"])
    minimum = b.slider("最低 Bull Flag Score", 0, 100, int(config.min_bull_flag_score))
    status = c.selectbox("Status", ["All", "FORMING", "BREAKOUT"], format_func=lambda x: LABELS.get(x, "全部"))
    a, b = st.columns(2)
    min_return = a.slider("最低旗桿漲幅 (%)", int(config.min_flagpole_return * 100), 100,
                          int(config.min_flagpole_return * 100)) / 100
    flag_days = b.slider("Flag Length（回歸交易日，不含最新 K 棒）", config.min_flag_days,
                         config.max_flag_days, (config.min_flag_days, config.max_flag_days))
    max_pullback = a.slider("最大旗桿回撤 (%)", 5, int(config.max_retracement * 100),
                            int(config.max_retracement * 100)) / 100
    max_volume = b.slider("最大旗形／旗桿平均量比", 0.1, 5.0, 5.0, 0.1)
    result = filter_candidates(snapshot["patterns"], market, minimum, min_return,
                               flag_days, max_pullback, max_volume, status)
    result["news_score"] = result.stock_code.map(snapshot["news_scores"])
    st.caption(f"符合篩選：{len(result)} 檔。News Score 使用既有最近 20 篇新聞的分析結果，與型態分數分開。")
    st.caption("80–100：強候選 · 70–79：觀察名單 · 60–69：弱候選 · 低於 60 分預設隱藏。")
    columns = ["rank", "stock_code", "stock_name", "market", "status", "close", "price_date",
               "flagpole_return_pct", "pullback_pct", "volume_ratio", "bull_flag_score", "news_score"]
    for tab, state in zip(st.tabs(["🟡 形成中", "🟢 突破"]), ("FORMING", "BREAKOUT")):
        with tab:
            selected = result[result.status == state].copy()
            if selected.empty:
                st.info("目前無符合條件的候選。")
            else:
                selected["status"] = selected.status.map(LABELS)
                selected["flagpole_return_pct"] *= 100
                selected["pullback_pct"] *= 100
                st.dataframe(selected[columns], hide_index=True, use_container_width=True,
                             column_config={
                                 "flagpole_return_pct": st.column_config.NumberColumn("旗桿漲幅 (%)", format="%.2f"),
                                 "pullback_pct": st.column_config.NumberColumn("高點回落 (%)", format="%.2f"),
                                 "news_score": st.column_config.NumberColumn("News Score", format="%.2f")})
    if result.empty:
        return
    st.download_button("下載候選 CSV", result.to_csv(index=False).encode("utf-8-sig"),
                       "bull_flag_candidates.csv", "text/csv")
    ticker = st.selectbox("查看個股", result.ticker.tolist(), format_func=lambda value:
                          f'{value} {result.loc[result.ticker == value, "stock_name"].iloc[0]}')
    row = result[result.ticker == ticker].iloc[0]
    st.subheader(f"{row.stock_code} {row.stock_name} · {row.market} · {LABELS[row.status]}")
    if row.price_breakout and row.status == "FORMING":
        st.info("價格已越過阻力線，成交量尚未確認；保留於形成中觀察。")
    st.dataframe(pd.DataFrame([row[["close", "price_date", "bull_flag_score", "news_score", "MA20", "MA60",
                                  "flagpole_return_pct", "pullback_pct", "retracement", "volume_ratio",
                                  "breakout_volume_ratio", "flag_days"]]]), hide_index=True)
    st.caption("詳細欄位 return_pct / pullback_pct / retracement 為小數比例（0.15 = 15%）。"
               "回撤是旗桿漲幅被回吐的比例，高點回落是相對旗桿高點的跌幅。")
    st.dataframe(pd.DataFrame([{"component": key[6:], "points": value}
                              for key, value in row.items() if key.startswith("score_")]), hide_index=True)
    data = snapshot["details"][ticker]
    st.plotly_chart(candidate_chart(data, row), use_container_width=True)
    volume = go.Figure(go.Bar(x=data.tail(100).index, y=data.Volume.tail(100), name="成交股數"))
    for name in ("Volume_MA5", "Volume_MA20"):
        volume.add_trace(go.Scatter(x=data.tail(100).index, y=data[name].tail(100), name=name))
    volume.update_layout(height=250, yaxis_title="股")
    st.plotly_chart(volume, use_container_width=True)
    st.caption("台北時間 14:00 前排除當日日線；請核對價格日期。歷史價格依 Adj Close 調整並錨定最新報價。"
               "分數是規則評分，尚未經績效回測。")
