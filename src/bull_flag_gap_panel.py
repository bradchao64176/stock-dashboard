"""Gap strategy UI: explicit scan snapshot, then local event filtering only."""
from dataclasses import asdict, replace

import pandas as pd
import streamlit as st

from src.bull_flag_gap import scan_gap_universe, filter_gap_events, STATUSES
from src.bull_flag_gap_config import GapConfig
from src.bull_flag_panel import cached_universe, cached_histories, candidate_chart

LABELS = {"UNTOUCHED": "🟢 未觸及", "PARTIALLY_FILLED": "🟡 部分回補", "FILLED": "🔴 完全回補"}


def gap_chart(data, event):
    # Reuse the scanner's candlestick/MA/regression renderer, with the marker at
    # the historical breakout rather than the latest observation.
    chart_row = event.copy()
    chart_row["price_date"] = event.breakout_date
    chart_row["close"] = event.breakout_close
    chart_row["status"] = "BREAKOUT"
    fig = candidate_chart(data, chart_row)
    fig.add_shape(type="rect", x0=event.gap_date, x1=event.price_date,
                  y0=event.gap_bottom, y1=event.gap_top,
                  fillcolor="orange", opacity=.22, line=dict(color="orange"), layer="below")
    fig.add_annotation(x=event.gap_date, y=event.gap_top, text="Original gap zone", showarrow=True)
    if pd.notna(event.gap_fill_date):
        fig.add_annotation(x=event.gap_fill_date, y=event.gap_bottom, text="Gap filled", showarrow=True)
    return fig


def render_gap_panel():
    st.title("下降旗形多方缺口突破選股")
    st.caption("Bull Flag Gap Breakout · 獨立策略 · 歷史旗形突破 + 多方缺口 + 回補追蹤")
    with st.expander("取得資料與搜尋事件", expanded="bull_flag_gap_snapshot" not in st.session_state):
        with st.form("bull_flag_gap_scan"):
            a, b, c = st.columns(3)
            market = a.selectbox("下載市場", ["All", "TWSE", "TPEx"])
            lookback = b.selectbox("Gap Lookback Days（交易日）", [5, 10, 20, 30, 60], index=2)
            definition = c.selectbox("Gap Definition", ["FULL_GAP", "OPEN_GAP"])
            window = a.selectbox("Gap / Breakout Window", [0, 1, 2],
                                  format_func=lambda n: "0：同日" if n == 0 else f"±{n} 交易日")
            limit = b.number_input("最多股票數（0 = 全市場）", 0, 3000, 20)
            codes = c.text_input("指定股票代碼（選填，逗號分隔）")
            refresh = a.checkbox("重新下載資料", value=False)
            submitted = st.form_submit_button("更新資料並搜尋缺口")
        st.caption("FULL_GAP：當日最低 > 前日最高；OPEN_GAP：當日開盤 > 前日最高，當日即可能回補。"
                   "初次建議 20 檔；設定 0 可掃全市場。改結果篩選不重新下載。")
        if submitted:
            try:
                if refresh:
                    cached_universe.clear()
                    cached_histories.clear()
                universe, errors = cached_universe()
                if market != "All":
                    universe = universe[universe.market == market]
                if codes.strip():
                    requested = {code.strip() for code in codes.replace("，", ",").split(",") if code.strip()}
                    missing = requested - set(universe.stock_code)
                    if missing:
                        st.warning(f"所選市場無這些普通股：{', '.join(sorted(missing))}")
                    universe = universe[universe.stock_code.isin(requested)]
                universe = universe.sort_values("stock_code")
                if limit:
                    universe = universe.head(int(limit))
                if universe.empty:
                    raise ValueError(f"無可用股票；官方名單錯誤：{errors}")
                with st.spinner("取得約一年行情與企業行動…"):
                    histories, failures = cached_histories(tuple(universe.ticker), include_actions=True)
                # Store the broad event set so all score/volume/gap-size filters
                # can be changed without regeneration or losing filled events.
                base = GapConfig()
                config = replace(base, detector=replace(base.detector, min_bull_flag_score=0),
                                 gap_lookback_days=lookback, gap_definition=definition,
                                 gap_breakout_window=window, min_gap_pct=0,
                                 require_gap_volume_confirmation=False)
                bar = st.progress(0.0, text="搜尋歷史突破缺口…")
                snapshot = scan_gap_universe(universe, histories, config,
                                             progress=lambda done, total: bar.progress(done / total, text=f"分析 {done}/{total}"))
                bar.empty()
                snapshot.update(universe_errors=errors, download_errors=failures)
                st.session_state["bull_flag_gap_snapshot"] = snapshot
            except Exception as error:
                st.error(f"搜尋失敗，保留先前快照：{error}")
    snapshot = st.session_state.get("bull_flag_gap_snapshot")
    if snapshot is None:
        st.info("按「更新資料並搜尋缺口」開始。此策略不會取代原選股器或回測頁面。")
        return
    config = snapshot["config"]
    st.caption(f'資料市場日：{snapshot["market_date"]} · 掃描 UTC：{snapshot["scan_time"]} · '
               f'{config.gap_definition} · 最近 {config.gap_lookback_days} 個交易日（含最新日）· '
               f'突破／缺口窗口 ±{config.gap_breakout_window} 日')
    for market, error in snapshot["universe_errors"].items():
        st.warning(f"{market} 官方名單失敗，涵蓋市場可能不完整：{error}")
    stats = snapshot["stats"]
    for col, label, value in zip(st.columns(4), ["股票數", "下載成功", "分析成功", "歷史缺口事件"],
                                [stats["total"], stats["downloaded"], stats["analyzed"], stats["events"]]):
        col.metric(label, value)
    with st.expander("資料驗證與錯誤紀錄"):
        st.write(snapshot["download_errors"])
        st.dataframe(pd.DataFrame(snapshot["issues"]), hide_index=True)
        st.json(asdict(config))
    a, b, c = st.columns(3)
    market = a.selectbox("Market", ["All", "TWSE", "TPEx"])
    minimum_gap = b.selectbox("Minimum Gap %", [0.0, .5, 1.0, 1.5, 2.0, 3.0, 5.0], index=2) / 100
    minimum_bull = c.slider("Minimum Bull Flag Score", 0, 100, 60)
    minimum_score = a.slider("Minimum Gap Breakout Score", 0, 100, 0)
    require_volume = b.checkbox("Breakout Volume Confirmation", value=True)
    ratio = c.number_input("Minimum Breakout Volume Ratio", 0.0, 10.0, 1.2, .1)
    statuses = a.multiselect("Gap Status", list(STATUSES), ["UNTOUCHED", "PARTIALLY_FILLED"],
                             format_func=lambda s: LABELS[s])
    untouched = b.checkbox("Only Untouched Gaps", value=False)
    selected = filter_gap_events(snapshot["events"], market=market, statuses=statuses, only_untouched=untouched,
                                 min_bull_flag_score=minimum_bull, min_gap_score=minimum_score,
                                 min_gap_pct=minimum_gap, require_volume=require_volume, min_volume_ratio=ratio)
    st.metric("符合條件股票", len(selected))
    st.caption("預設只顯示未觸及／部分回補；每檔取符合篩選的最新缺口。缺資料或後續價格基準變動的事件不認證為未回補。")
    if selected.empty:
        st.info("目前沒有符合條件的股票；沒有使用示範數字。")
        return
    table = selected[["rank", "stock_code", "stock_name", "market", "current_close", "gap_date",
                      "breakout_date", "trading_days_since_gap", "gap_pct", "gap_fill_pct", "gap_status",
                      "breakout_volume_ratio", "bull_flag_score", "gap_breakout_score"]].copy()
    table["gap_pct"] *= 100
    table["gap_fill_pct"] *= 100
    table["gap_status"] = table.gap_status.map(LABELS)
    st.dataframe(table, hide_index=True, use_container_width=True,
                 column_config={"gap_pct": st.column_config.NumberColumn("Gap %", format="%.2f"),
                                "gap_fill_pct": st.column_config.NumberColumn("Gap Fill %", format="%.2f")})
    st.download_button("下載選股 CSV", selected.to_csv(index=False).encode("utf-8-sig"), "gap_candidates.csv", "text/csv")
    st.download_button("下載全部事件 CSV", snapshot["events"].to_csv(index=False).encode("utf-8-sig"), "gap_events.csv", "text/csv")
    ticker = st.selectbox("查看個股", selected.ticker.tolist(), key=f'gap_stock_{snapshot["scan_time"]}')
    all_events = snapshot["events"][snapshot["events"].ticker == ticker].sort_values("gap_date", ascending=False)
    row = selected[selected.ticker == ticker].iloc[0]
    with st.expander("此股所有缺口事件（含已回補／未認證）"):
        st.dataframe(all_events, hide_index=True, use_container_width=True)
        st.caption("企業行動／缺資料警示以 fill_data_complete 顯示；false 的觀測狀態不可視為已確認。")
    inspect_all = st.checkbox("檢視此股其他歷史事件", value=False)
    if inspect_all:
        event_id = st.selectbox("Gap Event", all_events.event_id.tolist(), key=f'gap_event_{ticker}_{snapshot["scan_time"]}')
        row = all_events[all_events.event_id == event_id].iloc[0]
    st.subheader(f'{row.stock_code} {row.stock_name} · {LABELS[row.gap_status]}')
    st.caption(f'突破：{row.breakout_date.date()} · 缺口：{row.gap_date.date()} · '
               f'Gap {row.gap_pct:.2%} · 回補 {row.gap_fill_pct:.2%} · 現價 {row.current_close:,.2f}')
    st.dataframe(pd.DataFrame([row[["gap_bottom", "gap_top", "gap_size", "remaining_gap_size", "remaining_gap_pct",
                                   "lowest_price_after_gap", "gap_fill_date", "days_until_gap_fill",
                                   "distance_from_gap_pct", "MA20", "MA60", "bull_flag_score", "gap_breakout_score"]]]), hide_index=True)
    st.dataframe(pd.DataFrame([dict(component=key[10:], points=value) for key, value in row.items()
                              if key.startswith("gap_score_") and key != "gap_score_at_signal"]), hide_index=True)
    st.plotly_chart(gap_chart(snapshot["details"][ticker], row), use_container_width=True)
    st.caption("成交量分母為突破前 20 根均量，不含突破日。交易日曆由本次下載股票的實際有量日期聯集推定。"
               "企業行動、Yahoo 缺漏／追溯修正可能造成漏選；Gap Score 是規則分數，非獲利機率。")
